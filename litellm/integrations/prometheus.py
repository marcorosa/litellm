# used for /metrics endpoint on LiteLLM Proxy
#### What this does ####
#    On success, log events to Prometheus
import asyncio
import sys
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, List, Literal, Optional, Tuple, cast

import litellm
from litellm._logging import print_verbose, verbose_logger
from litellm.integrations.custom_logger import CustomLogger
from litellm.proxy._types import LiteLLM_TeamTable, UserAPIKeyAuth
from litellm.types.integrations.prometheus import *
from litellm.types.utils import StandardLoggingPayload
from litellm.utils import get_end_user_id_for_cost_tracking


class PrometheusLogger(CustomLogger):
    # Class variables or attributes
    def __init__(
        self,
        **kwargs,
    ):
        try:
            from prometheus_client import Counter, Gauge, Histogram

            from litellm.proxy.proxy_server import CommonProxyErrors, premium_user

            if premium_user is not True:
                verbose_logger.warning(
                    f"🚨🚨🚨 Prometheus Metrics is on LiteLLM Enterprise\n🚨 {CommonProxyErrors.not_premium_user.value}"
                )
                self.litellm_not_a_premium_user_metric = Counter(
                    name="litellm_not_a_premium_user_metric",
                    documentation=f"🚨🚨🚨 Prometheus Metrics is on LiteLLM Enterprise. 🚨 {CommonProxyErrors.not_premium_user.value}",
                )
                return

            self.litellm_proxy_failed_requests_metric = Counter(
                name="litellm_proxy_failed_requests_metric",
                documentation="Total number of failed responses from proxy - the client did not get a success response from litellm proxy",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_proxy_failed_requests_metric"
                ),
            )

            self.litellm_proxy_total_requests_metric = Counter(
                name="litellm_proxy_total_requests_metric",
                documentation="Total number of requests made to the proxy server - track number of client side requests",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_proxy_total_requests_metric"
                ),
            )

            # request latency metrics
            self.litellm_request_total_latency_metric = Histogram(
                "litellm_request_total_latency_metric",
                "Total latency (seconds) for a request to LiteLLM",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_request_total_latency_metric"
                ),
                buckets=LATENCY_BUCKETS,
            )

            self.litellm_llm_api_latency_metric = Histogram(
                "litellm_llm_api_latency_metric",
                "Total latency (seconds) for a models LLM API call",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_llm_api_latency_metric"
                ),
                buckets=LATENCY_BUCKETS,
            )

            self.litellm_llm_api_time_to_first_token_metric = Histogram(
                "litellm_llm_api_time_to_first_token_metric",
                "Time to first token for a models LLM API call",
                labelnames=[
                    "model",
                    "hashed_api_key",
                    "api_key_alias",
                    "team",
                    "team_alias",
                ],
                buckets=LATENCY_BUCKETS,
            )

            # Counter for spend
            self.litellm_spend_metric = Counter(
                "litellm_spend_metric",
                "Total spend on LLM requests",
                labelnames=[
                    "end_user",
                    "hashed_api_key",
                    "api_key_alias",
                    "model",
                    "team",
                    "team_alias",
                    "user",
                ],
            )

            # Counter for total_output_tokens
            self.litellm_tokens_metric = Counter(
                "litellm_total_tokens",
                "Total number of input + output tokens from LLM requests",
                labelnames=[
                    "end_user",
                    "hashed_api_key",
                    "api_key_alias",
                    "model",
                    "team",
                    "team_alias",
                    "user",
                ],
            )

            self.litellm_input_tokens_metric = Counter(
                "litellm_input_tokens",
                "Total number of input tokens from LLM requests",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_input_tokens_metric"
                ),
            )

            self.litellm_output_tokens_metric = Counter(
                "litellm_output_tokens",
                "Total number of output tokens from LLM requests",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_output_tokens_metric"
                ),
            )

            # Remaining Budget for Team
            self.litellm_remaining_team_budget_metric = Gauge(
                "litellm_remaining_team_budget_metric",
                "Remaining budget for team",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_remaining_team_budget_metric"
                ),
            )

            # Max Budget for Team
            self.litellm_team_max_budget_metric = Gauge(
                "litellm_team_max_budget_metric",
                "Maximum budget set for team",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_team_max_budget_metric"
                ),
            )

            # Team Budget Reset At
            self.litellm_team_budget_remaining_hours_metric = Gauge(
                "litellm_team_budget_remaining_hours_metric",
                "Remaining days for team budget to be reset",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_team_budget_remaining_hours_metric"
                ),
            )

            # Remaining Budget for API Key
            self.litellm_remaining_api_key_budget_metric = Gauge(
                "litellm_remaining_api_key_budget_metric",
                "Remaining budget for api key",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_remaining_api_key_budget_metric"
                ),
            )

            # Max Budget for API Key
            self.litellm_api_key_max_budget_metric = Gauge(
                "litellm_api_key_max_budget_metric",
                "Maximum budget set for api key",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_api_key_max_budget_metric"
                ),
            )

            self.litellm_api_key_budget_remaining_hours_metric = Gauge(
                "litellm_api_key_budget_remaining_hours_metric",
                "Remaining hours for api key budget to be reset",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_api_key_budget_remaining_hours_metric"
                ),
            )

            ########################################
            # LiteLLM Virtual API KEY metrics
            ########################################
            # Remaining MODEL RPM limit for API Key
            self.litellm_remaining_api_key_requests_for_model = Gauge(
                "litellm_remaining_api_key_requests_for_model",
                "Remaining Requests API Key can make for model (model based rpm limit on key)",
                labelnames=["hashed_api_key", "api_key_alias", "model"],
            )

            # Remaining MODEL TPM limit for API Key
            self.litellm_remaining_api_key_tokens_for_model = Gauge(
                "litellm_remaining_api_key_tokens_for_model",
                "Remaining Tokens API Key can make for model (model based tpm limit on key)",
                labelnames=["hashed_api_key", "api_key_alias", "model"],
            )

            ########################################
            # LLM API Deployment Metrics / analytics
            ########################################

            # Remaining Rate Limit for model
            self.litellm_remaining_requests_metric = Gauge(
                "litellm_remaining_requests",
                "LLM Deployment Analytics - remaining requests for model, returned from LLM API Provider",
                labelnames=[
                    "model_group",
                    "api_provider",
                    "api_base",
                    "litellm_model_name",
                    "hashed_api_key",
                    "api_key_alias",
                ],
            )

            self.litellm_remaining_tokens_metric = Gauge(
                "litellm_remaining_tokens",
                "remaining tokens for model, returned from LLM API Provider",
                labelnames=[
                    "model_group",
                    "api_provider",
                    "api_base",
                    "litellm_model_name",
                    "hashed_api_key",
                    "api_key_alias",
                ],
            )

            self.litellm_overhead_latency_metric = Histogram(
                "litellm_overhead_latency_metric",
                "Latency overhead (milliseconds) added by LiteLLM processing",
                labelnames=[
                    "model_group",
                    "api_provider",
                    "api_base",
                    "litellm_model_name",
                    "hashed_api_key",
                    "api_key_alias",
                ],
                buckets=LATENCY_BUCKETS,
            )
            # llm api provider budget metrics
            self.litellm_provider_remaining_budget_metric = Gauge(
                "litellm_provider_remaining_budget_metric",
                "Remaining budget for provider - used when you set provider budget limits",
                labelnames=["api_provider"],
            )

            # Get all keys
            _logged_llm_labels = [
                UserAPIKeyLabelNames.v2_LITELLM_MODEL_NAME.value,
                UserAPIKeyLabelNames.MODEL_ID.value,
                UserAPIKeyLabelNames.API_BASE.value,
                UserAPIKeyLabelNames.API_PROVIDER.value,
            ]
            team_and_key_labels = [
                "hashed_api_key",
                "api_key_alias",
                "team",
                "team_alias",
            ]

            # Metric for deployment state
            self.litellm_deployment_state = Gauge(
                "litellm_deployment_state",
                "LLM Deployment Analytics - The state of the deployment: 0 = healthy, 1 = partial outage, 2 = complete outage",
                labelnames=_logged_llm_labels,
            )

            self.litellm_deployment_cooled_down = Counter(
                "litellm_deployment_cooled_down",
                "LLM Deployment Analytics - Number of times a deployment has been cooled down by LiteLLM load balancing logic. exception_status is the status of the exception that caused the deployment to be cooled down",
                labelnames=_logged_llm_labels + [EXCEPTION_STATUS],
            )

            self.litellm_deployment_success_responses = Counter(
                name="litellm_deployment_success_responses",
                documentation="LLM Deployment Analytics - Total number of successful LLM API calls via litellm",
                labelnames=[REQUESTED_MODEL] + _logged_llm_labels + team_and_key_labels,
            )
            self.litellm_deployment_failure_responses = Counter(
                name="litellm_deployment_failure_responses",
                documentation="LLM Deployment Analytics - Total number of failed LLM API calls for a specific LLM deploymeny. exception_status is the status of the exception from the llm api",
                labelnames=[REQUESTED_MODEL]
                + _logged_llm_labels
                + EXCEPTION_LABELS
                + team_and_key_labels,
            )
            self.litellm_deployment_failure_by_tag_responses = Counter(
                "litellm_deployment_failure_by_tag_responses",
                "Total number of failed LLM API calls for a specific LLM deploymeny by custom metadata tags",
                labelnames=[
                    UserAPIKeyLabelNames.REQUESTED_MODEL.value,
                    UserAPIKeyLabelNames.TAG.value,
                ]
                + _logged_llm_labels
                + EXCEPTION_LABELS,
            )
            self.litellm_deployment_total_requests = Counter(
                name="litellm_deployment_total_requests",
                documentation="LLM Deployment Analytics - Total number of LLM API calls via litellm - success + failure",
                labelnames=[REQUESTED_MODEL] + _logged_llm_labels + team_and_key_labels,
            )

            # Deployment Latency tracking
            team_and_key_labels = [
                "hashed_api_key",
                "api_key_alias",
                "team",
                "team_alias",
            ]
            self.litellm_deployment_latency_per_output_token = Histogram(
                name="litellm_deployment_latency_per_output_token",
                documentation="LLM Deployment Analytics - Latency per output token",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_deployment_latency_per_output_token"
                ),
            )

            self.litellm_deployment_successful_fallbacks = Counter(
                "litellm_deployment_successful_fallbacks",
                "LLM Deployment Analytics - Number of successful fallback requests from primary model -> fallback model",
                PrometheusMetricLabels.get_labels(
                    "litellm_deployment_successful_fallbacks"
                ),
            )

            self.litellm_deployment_failed_fallbacks = Counter(
                "litellm_deployment_failed_fallbacks",
                "LLM Deployment Analytics - Number of failed fallback requests from primary model -> fallback model",
                PrometheusMetricLabels.get_labels(
                    "litellm_deployment_failed_fallbacks"
                ),
            )

            self.litellm_llm_api_failed_requests_metric = Counter(
                name="litellm_llm_api_failed_requests_metric",
                documentation="deprecated - use litellm_proxy_failed_requests_metric",
                labelnames=[
                    "end_user",
                    "hashed_api_key",
                    "api_key_alias",
                    "model",
                    "team",
                    "team_alias",
                    "user",
                ],
            )

            self.litellm_requests_metric = Counter(
                name="litellm_requests_metric",
                documentation="deprecated - use litellm_proxy_total_requests_metric. Total number of LLM calls to litellm - track total per API Key, team, user",
                labelnames=PrometheusMetricLabels.get_labels(
                    label_name="litellm_requests_metric"
                ),
            )
            self._initialize_prometheus_startup_metrics()

        except Exception as e:
            print_verbose(f"Got exception on init prometheus client {str(e)}")
            raise e

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        # Define prometheus client
        from litellm.types.utils import StandardLoggingPayload

        verbose_logger.debug(
            f"prometheus Logging - Enters success logging function for kwargs {kwargs}"
        )

        # unpack kwargs
        standard_logging_payload: Optional[StandardLoggingPayload] = kwargs.get(
            "standard_logging_object"
        )

        if standard_logging_payload is None or not isinstance(
            standard_logging_payload, dict
        ):
            raise ValueError(
                f"standard_logging_object is required, got={standard_logging_payload}"
            )

        model = kwargs.get("model", "")
        litellm_params = kwargs.get("litellm_params", {}) or {}
        _metadata = litellm_params.get("metadata", {})
        end_user_id = get_end_user_id_for_cost_tracking(
            litellm_params, service_type="prometheus"
        )
        user_id = standard_logging_payload["metadata"]["user_api_key_user_id"]
        user_api_key = standard_logging_payload["metadata"]["user_api_key_hash"]
        user_api_key_alias = standard_logging_payload["metadata"]["user_api_key_alias"]
        user_api_team = standard_logging_payload["metadata"]["user_api_key_team_id"]
        user_api_team_alias = standard_logging_payload["metadata"][
            "user_api_key_team_alias"
        ]
        output_tokens = standard_logging_payload["completion_tokens"]
        tokens_used = standard_logging_payload["total_tokens"]
        response_cost = standard_logging_payload["response_cost"]
        _requester_metadata = standard_logging_payload["metadata"].get(
            "requester_metadata"
        )
        if standard_logging_payload is not None and isinstance(
            standard_logging_payload, dict
        ):
            _tags = standard_logging_payload["request_tags"]
        else:
            _tags = []

        print_verbose(
            f"inside track_prometheus_metrics, model {model}, response_cost {response_cost}, tokens_used {tokens_used}, end_user_id {end_user_id}, user_api_key {user_api_key}"
        )

        enum_values = UserAPIKeyLabelValues(
            end_user=end_user_id,
            hashed_api_key=user_api_key,
            api_key_alias=user_api_key_alias,
            requested_model=standard_logging_payload["model_group"],
            team=user_api_team,
            team_alias=user_api_team_alias,
            user=user_id,
            user_email=standard_logging_payload["metadata"]["user_api_key_user_email"],
            status_code="200",
            model=model,
            litellm_model_name=model,
            tags=_tags,
            model_id=standard_logging_payload["model_id"],
            api_base=standard_logging_payload["api_base"],
            api_provider=standard_logging_payload["custom_llm_provider"],
            exception_status=None,
            exception_class=None,
            custom_metadata_labels=get_custom_labels_from_metadata(
                metadata=standard_logging_payload["metadata"].get("requester_metadata")
                or {}
            ),
        )

        if (
            user_api_key is not None
            and isinstance(user_api_key, str)
            and user_api_key.startswith("sk-")
        ):
            from litellm.proxy.utils import hash_token

            user_api_key = hash_token(user_api_key)

        # increment total LLM requests and spend metric
        self._increment_top_level_request_and_spend_metrics(
            end_user_id=end_user_id,
            user_api_key=user_api_key,
            user_api_key_alias=user_api_key_alias,
            model=model,
            user_api_team=user_api_team,
            user_api_team_alias=user_api_team_alias,
            user_id=user_id,
            response_cost=response_cost,
            enum_values=enum_values,
        )

        # input, output, total token metrics
        self._increment_token_metrics(
            # why type ignore below?
            # 1. We just checked if isinstance(standard_logging_payload, dict). Pyright complains.
            # 2. Pyright does not allow us to run isinstance(standard_logging_payload, StandardLoggingPayload) <- this would be ideal
            standard_logging_payload=standard_logging_payload,  # type: ignore
            end_user_id=end_user_id,
            user_api_key=user_api_key,
            user_api_key_alias=user_api_key_alias,
            model=model,
            user_api_team=user_api_team,
            user_api_team_alias=user_api_team_alias,
            user_id=user_id,
            enum_values=enum_values,
        )

        # remaining budget metrics
        await self._increment_remaining_budget_metrics(
            user_api_team=user_api_team,
            user_api_team_alias=user_api_team_alias,
            user_api_key=user_api_key,
            user_api_key_alias=user_api_key_alias,
            litellm_params=litellm_params,
            response_cost=response_cost,
        )

        # set proxy virtual key rpm/tpm metrics
        self._set_virtual_key_rate_limit_metrics(
            user_api_key=user_api_key,
            user_api_key_alias=user_api_key_alias,
            kwargs=kwargs,
            metadata=_metadata,
        )

        # set latency metrics
        self._set_latency_metrics(
            kwargs=kwargs,
            model=model,
            user_api_key=user_api_key,
            user_api_key_alias=user_api_key_alias,
            user_api_team=user_api_team,
            user_api_team_alias=user_api_team_alias,
            # why type ignore below?
            # 1. We just checked if isinstance(standard_logging_payload, dict). Pyright complains.
            # 2. Pyright does not allow us to run isinstance(standard_logging_payload, StandardLoggingPayload) <- this would be ideal
            enum_values=enum_values,
        )

        # set x-ratelimit headers
        self.set_llm_deployment_success_metrics(
            kwargs, start_time, end_time, enum_values, output_tokens
        )

        if (
            standard_logging_payload["stream"] is True
        ):  # log successful streaming requests from logging event hook.
            _labels = prometheus_label_factory(
                supported_enum_labels=PrometheusMetricLabels.get_labels(
                    label_name="litellm_proxy_total_requests_metric"
                ),
                enum_values=enum_values,
            )
            self.litellm_proxy_total_requests_metric.labels(**_labels).inc()

    def _increment_token_metrics(
        self,
        standard_logging_payload: StandardLoggingPayload,
        end_user_id: Optional[str],
        user_api_key: Optional[str],
        user_api_key_alias: Optional[str],
        model: Optional[str],
        user_api_team: Optional[str],
        user_api_team_alias: Optional[str],
        user_id: Optional[str],
        enum_values: UserAPIKeyLabelValues,
    ):
        # token metrics
        self.litellm_tokens_metric.labels(
            end_user_id,
            user_api_key,
            user_api_key_alias,
            model,
            user_api_team,
            user_api_team_alias,
            user_id,
        ).inc(standard_logging_payload["total_tokens"])

        if standard_logging_payload is not None and isinstance(
            standard_logging_payload, dict
        ):
            _tags = standard_logging_payload["request_tags"]

        _labels = prometheus_label_factory(
            supported_enum_labels=PrometheusMetricLabels.get_labels(
                label_name="litellm_input_tokens_metric"
            ),
            enum_values=enum_values,
        )
        self.litellm_input_tokens_metric.labels(**_labels).inc(
            standard_logging_payload["prompt_tokens"]
        )

        _labels = prometheus_label_factory(
            supported_enum_labels=PrometheusMetricLabels.get_labels(
                label_name="litellm_output_tokens_metric"
            ),
            enum_values=enum_values,
        )

        self.litellm_output_tokens_metric.labels(**_labels).inc(
            standard_logging_payload["completion_tokens"]
        )

    async def _increment_remaining_budget_metrics(
        self,
        user_api_team: Optional[str],
        user_api_team_alias: Optional[str],
        user_api_key: Optional[str],
        user_api_key_alias: Optional[str],
        litellm_params: dict,
        response_cost: float,
    ):
        _team_spend = litellm_params.get("metadata", {}).get(
            "user_api_key_team_spend", None
        )
        _team_max_budget = litellm_params.get("metadata", {}).get(
            "user_api_key_team_max_budget", None
        )

        _api_key_spend = litellm_params.get("metadata", {}).get(
            "user_api_key_spend", None
        )
        _api_key_max_budget = litellm_params.get("metadata", {}).get(
            "user_api_key_max_budget", None
        )
        await self._set_api_key_budget_metrics_after_api_request(
            user_api_key=user_api_key,
            user_api_key_alias=user_api_key_alias,
            response_cost=response_cost,
            key_max_budget=_api_key_max_budget,
            key_spend=_api_key_spend,
        )

        await self._set_team_budget_metrics_after_api_request(
            user_api_team=user_api_team,
            user_api_team_alias=user_api_team_alias,
            team_spend=_team_spend,
            team_max_budget=_team_max_budget,
            response_cost=response_cost,
        )

    def _increment_top_level_request_and_spend_metrics(
        self,
        end_user_id: Optional[str],
        user_api_key: Optional[str],
        user_api_key_alias: Optional[str],
        model: Optional[str],
        user_api_team: Optional[str],
        user_api_team_alias: Optional[str],
        user_id: Optional[str],
        response_cost: float,
        enum_values: UserAPIKeyLabelValues,
    ):
        _labels = prometheus_label_factory(
            supported_enum_labels=PrometheusMetricLabels.get_labels(
                label_name="litellm_requests_metric"
            ),
            enum_values=enum_values,
        )
        self.litellm_requests_metric.labels(**_labels).inc()

        self.litellm_spend_metric.labels(
            end_user_id,
            user_api_key,
            user_api_key_alias,
            model,
            user_api_team,
            user_api_team_alias,
            user_id,
        ).inc(response_cost)

    def _set_virtual_key_rate_limit_metrics(
        self,
        user_api_key: Optional[str],
        user_api_key_alias: Optional[str],
        kwargs: dict,
        metadata: dict,
    ):
        from litellm.proxy.common_utils.callback_utils import (
            get_model_group_from_litellm_kwargs,
        )

        # Set remaining rpm/tpm for API Key + model
        # see parallel_request_limiter.py - variables are set there
        model_group = get_model_group_from_litellm_kwargs(kwargs)
        remaining_requests_variable_name = (
            f"litellm-key-remaining-requests-{model_group}"
        )
        remaining_tokens_variable_name = f"litellm-key-remaining-tokens-{model_group}"

        remaining_requests = (
            metadata.get(remaining_requests_variable_name, sys.maxsize) or sys.maxsize
        )
        remaining_tokens = (
            metadata.get(remaining_tokens_variable_name, sys.maxsize) or sys.maxsize
        )

        self.litellm_remaining_api_key_requests_for_model.labels(
            user_api_key, user_api_key_alias, model_group
        ).set(remaining_requests)

        self.litellm_remaining_api_key_tokens_for_model.labels(
            user_api_key, user_api_key_alias, model_group
        ).set(remaining_tokens)

    def _set_latency_metrics(
        self,
        kwargs: dict,
        model: Optional[str],
        user_api_key: Optional[str],
        user_api_key_alias: Optional[str],
        user_api_team: Optional[str],
        user_api_team_alias: Optional[str],
        enum_values: UserAPIKeyLabelValues,
    ):
        # latency metrics
        end_time: datetime = kwargs.get("end_time") or datetime.now()
        start_time: Optional[datetime] = kwargs.get("start_time")
        api_call_start_time = kwargs.get("api_call_start_time", None)
        completion_start_time = kwargs.get("completion_start_time", None)
        time_to_first_token_seconds = self._safe_duration_seconds(
            start_time=api_call_start_time,
            end_time=completion_start_time,
        )
        if (
            time_to_first_token_seconds is not None
            and kwargs.get("stream", False) is True  # only emit for streaming requests
        ):
            self.litellm_llm_api_time_to_first_token_metric.labels(
                model,
                user_api_key,
                user_api_key_alias,
                user_api_team,
                user_api_team_alias,
            ).observe(time_to_first_token_seconds)
        else:
            verbose_logger.debug(
                "Time to first token metric not emitted, stream option in model_parameters is not True"
            )

        api_call_total_time_seconds = self._safe_duration_seconds(
            start_time=api_call_start_time,
            end_time=end_time,
        )
        if api_call_total_time_seconds is not None:
            _labels = prometheus_label_factory(
                supported_enum_labels=PrometheusMetricLabels.get_labels(
                    label_name="litellm_llm_api_latency_metric"
                ),
                enum_values=enum_values,
            )
            self.litellm_llm_api_latency_metric.labels(**_labels).observe(
                api_call_total_time_seconds
            )

        # total request latency
        total_time_seconds = self._safe_duration_seconds(
            start_time=start_time,
            end_time=end_time,
        )
        if total_time_seconds is not None:
            _labels = prometheus_label_factory(
                supported_enum_labels=PrometheusMetricLabels.get_labels(
                    label_name="litellm_request_total_latency_metric"
                ),
                enum_values=enum_values,
            )
            self.litellm_request_total_latency_metric.labels(**_labels).observe(
                total_time_seconds
            )

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        from litellm.types.utils import StandardLoggingPayload

        verbose_logger.debug(
            f"prometheus Logging - Enters failure logging function for kwargs {kwargs}"
        )

        # unpack kwargs
        model = kwargs.get("model", "")
        standard_logging_payload: StandardLoggingPayload = kwargs.get(
            "standard_logging_object", {}
        )
        litellm_params = kwargs.get("litellm_params", {}) or {}
        end_user_id = get_end_user_id_for_cost_tracking(
            litellm_params, service_type="prometheus"
        )
        user_id = standard_logging_payload["metadata"]["user_api_key_user_id"]
        user_api_key = standard_logging_payload["metadata"]["user_api_key_hash"]
        user_api_key_alias = standard_logging_payload["metadata"]["user_api_key_alias"]
        user_api_team = standard_logging_payload["metadata"]["user_api_key_team_id"]
        user_api_team_alias = standard_logging_payload["metadata"][
            "user_api_key_team_alias"
        ]
        kwargs.get("exception", None)

        try:
            self.litellm_llm_api_failed_requests_metric.labels(
                end_user_id,
                user_api_key,
                user_api_key_alias,
                model,
                user_api_team,
                user_api_team_alias,
                user_id,
            ).inc()
            self.set_llm_deployment_failure_metrics(kwargs)
        except Exception as e:
            verbose_logger.exception(
                "prometheus Layer Error(): Exception occured - {}".format(str(e))
            )
            pass
        pass

    async def async_post_call_failure_hook(
        self,
        request_data: dict,
        original_exception: Exception,
        user_api_key_dict: UserAPIKeyAuth,
    ):
        """
        Track client side failures

        Proxy level tracking - failed client side requests

        labelnames=[
                    "end_user",
                    "hashed_api_key",
                    "api_key_alias",
                    REQUESTED_MODEL,
                    "team",
                    "team_alias",
                ] + EXCEPTION_LABELS,
        """
        try:
            _tags = cast(List[str], request_data.get("tags") or [])
            enum_values = UserAPIKeyLabelValues(
                end_user=user_api_key_dict.end_user_id,
                user=user_api_key_dict.user_id,
                user_email=user_api_key_dict.user_email,
                hashed_api_key=user_api_key_dict.api_key,
                api_key_alias=user_api_key_dict.key_alias,
                team=user_api_key_dict.team_id,
                team_alias=user_api_key_dict.team_alias,
                requested_model=request_data.get("model", ""),
                status_code=str(getattr(original_exception, "status_code", None)),
                exception_status=str(getattr(original_exception, "status_code", None)),
                exception_class=str(original_exception.__class__.__name__),
                tags=_tags,
            )
            _labels = prometheus_label_factory(
                supported_enum_labels=PrometheusMetricLabels.get_labels(
                    label_name="litellm_proxy_failed_requests_metric"
                ),
                enum_values=enum_values,
            )
            self.litellm_proxy_failed_requests_metric.labels(**_labels).inc()

            _labels = prometheus_label_factory(
                supported_enum_labels=PrometheusMetricLabels.get_labels(
                    label_name="litellm_proxy_total_requests_metric"
                ),
                enum_values=enum_values,
            )
            self.litellm_proxy_total_requests_metric.labels(**_labels).inc()

        except Exception as e:
            verbose_logger.exception(
                "prometheus Layer Error(): Exception occured - {}".format(str(e))
            )
            pass

    async def async_post_call_success_hook(
        self, data: dict, user_api_key_dict: UserAPIKeyAuth, response
    ):
        """
        Proxy level tracking - triggered when the proxy responds with a success response to the client
        """
        try:
            enum_values = UserAPIKeyLabelValues(
                end_user=user_api_key_dict.end_user_id,
                hashed_api_key=user_api_key_dict.api_key,
                api_key_alias=user_api_key_dict.key_alias,
                requested_model=data.get("model", ""),
                team=user_api_key_dict.team_id,
                team_alias=user_api_key_dict.team_alias,
                user=user_api_key_dict.user_id,
                user_email=user_api_key_dict.user_email,
                status_code="200",
            )
            _labels = prometheus_label_factory(
                supported_enum_labels=PrometheusMetricLabels.get_labels(
                    label_name="litellm_proxy_total_requests_metric"
                ),
                enum_values=enum_values,
            )
            self.litellm_proxy_total_requests_metric.labels(**_labels).inc()

        except Exception as e:
            verbose_logger.exception(
                "prometheus Layer Error(): Exception occured - {}".format(str(e))
            )
            pass

    def set_llm_deployment_failure_metrics(self, request_kwargs: dict):
        """
        Sets Failure metrics when an LLM API call fails

        - mark the deployment as partial outage
        - increment deployment failure responses metric
        - increment deployment total requests metric

        Args:
            request_kwargs: dict

        """
        try:
            verbose_logger.debug("setting remaining tokens requests metric")
            standard_logging_payload: StandardLoggingPayload = request_kwargs.get(
                "standard_logging_object", {}
            )
            _litellm_params = request_kwargs.get("litellm_params", {}) or {}
            litellm_model_name = request_kwargs.get("model", None)
            model_group = standard_logging_payload.get("model_group", None)
            api_base = standard_logging_payload.get("api_base", None)
            model_id = standard_logging_payload.get("model_id", None)
            exception: Exception = request_kwargs.get("exception", None)

            llm_provider = _litellm_params.get("custom_llm_provider", None)

            """
            log these labels
            ["litellm_model_name", "model_id", "api_base", "api_provider"]
            """
            self.set_deployment_partial_outage(
                litellm_model_name=litellm_model_name,
                model_id=model_id,
                api_base=api_base,
                api_provider=llm_provider,
            )
            self.litellm_deployment_failure_responses.labels(
                litellm_model_name=litellm_model_name,
                model_id=model_id,
                api_base=api_base,
                api_provider=llm_provider,
                exception_status=str(getattr(exception, "status_code", None)),
                exception_class=exception.__class__.__name__,
                requested_model=model_group,
                hashed_api_key=standard_logging_payload["metadata"][
                    "user_api_key_hash"
                ],
                api_key_alias=standard_logging_payload["metadata"][
                    "user_api_key_alias"
                ],
                team=standard_logging_payload["metadata"]["user_api_key_team_id"],
                team_alias=standard_logging_payload["metadata"][
                    "user_api_key_team_alias"
                ],
            ).inc()

            # tag based tracking
            if standard_logging_payload is not None and isinstance(
                standard_logging_payload, dict
            ):
                _tags = standard_logging_payload["request_tags"]
                for tag in _tags:
                    self.litellm_deployment_failure_by_tag_responses.labels(
                        **{
                            UserAPIKeyLabelNames.REQUESTED_MODEL.value: model_group,
                            UserAPIKeyLabelNames.TAG.value: tag,
                            UserAPIKeyLabelNames.v2_LITELLM_MODEL_NAME.value: litellm_model_name,
                            UserAPIKeyLabelNames.MODEL_ID.value: model_id,
                            UserAPIKeyLabelNames.API_BASE.value: api_base,
                            UserAPIKeyLabelNames.API_PROVIDER.value: llm_provider,
                            UserAPIKeyLabelNames.EXCEPTION_CLASS.value: exception.__class__.__name__,
                            UserAPIKeyLabelNames.EXCEPTION_STATUS.value: str(
                                getattr(exception, "status_code", None)
                            ),
                        }
                    ).inc()

            self.litellm_deployment_total_requests.labels(
                litellm_model_name=litellm_model_name,
                model_id=model_id,
                api_base=api_base,
                api_provider=llm_provider,
                requested_model=model_group,
                hashed_api_key=standard_logging_payload["metadata"][
                    "user_api_key_hash"
                ],
                api_key_alias=standard_logging_payload["metadata"][
                    "user_api_key_alias"
                ],
                team=standard_logging_payload["metadata"]["user_api_key_team_id"],
                team_alias=standard_logging_payload["metadata"][
                    "user_api_key_team_alias"
                ],
            ).inc()

            pass
        except Exception as e:
            verbose_logger.debug(
                "Prometheus Error: set_llm_deployment_failure_metrics. Exception occured - {}".format(
                    str(e)
                )
            )

    def set_llm_deployment_success_metrics(
        self,
        request_kwargs: dict,
        start_time,
        end_time,
        enum_values: UserAPIKeyLabelValues,
        output_tokens: float = 1.0,
    ):
        try:
            verbose_logger.debug("setting remaining tokens requests metric")
            standard_logging_payload: Optional[StandardLoggingPayload] = (
                request_kwargs.get("standard_logging_object")
            )

            if standard_logging_payload is None:
                return

            model_group = standard_logging_payload["model_group"]
            api_base = standard_logging_payload["api_base"]
            _response_headers = request_kwargs.get("response_headers")
            _litellm_params = request_kwargs.get("litellm_params", {}) or {}
            _metadata = _litellm_params.get("metadata", {})
            litellm_model_name = request_kwargs.get("model", None)
            llm_provider = _litellm_params.get("custom_llm_provider", None)
            _model_info = _metadata.get("model_info") or {}
            model_id = _model_info.get("id", None)

            remaining_requests: Optional[int] = None
            remaining_tokens: Optional[int] = None
            if additional_headers := standard_logging_payload["hidden_params"][
                "additional_headers"
            ]:
                # OpenAI / OpenAI Compatible headers
                remaining_requests = additional_headers.get(
                    "x_ratelimit_remaining_requests", None
                )
                remaining_tokens = additional_headers.get(
                    "x_ratelimit_remaining_tokens", None
                )

            if litellm_overhead_time_ms := standard_logging_payload[
                "hidden_params"
            ].get("litellm_overhead_time_ms"):
                self.litellm_overhead_latency_metric.labels(
                    model_group,
                    llm_provider,
                    api_base,
                    litellm_model_name,
                    standard_logging_payload["metadata"]["user_api_key_hash"],
                    standard_logging_payload["metadata"]["user_api_key_alias"],
                ).observe(
                    litellm_overhead_time_ms / 1000
                )  # set as seconds

            if remaining_requests:
                """
                "model_group",
                "api_provider",
                "api_base",
                "litellm_model_name"
                """
                self.litellm_remaining_requests_metric.labels(
                    model_group,
                    llm_provider,
                    api_base,
                    litellm_model_name,
                    standard_logging_payload["metadata"]["user_api_key_hash"],
                    standard_logging_payload["metadata"]["user_api_key_alias"],
                ).set(remaining_requests)

            if remaining_tokens:
                self.litellm_remaining_tokens_metric.labels(
                    model_group,
                    llm_provider,
                    api_base,
                    litellm_model_name,
                    standard_logging_payload["metadata"]["user_api_key_hash"],
                    standard_logging_payload["metadata"]["user_api_key_alias"],
                ).set(remaining_tokens)

            """
            log these labels
            ["litellm_model_name", "requested_model", model_id", "api_base", "api_provider"]
            """
            self.set_deployment_healthy(
                litellm_model_name=litellm_model_name,
                model_id=model_id,
                api_base=api_base,
                api_provider=llm_provider,
            )

            self.litellm_deployment_success_responses.labels(
                litellm_model_name=litellm_model_name,
                model_id=model_id,
                api_base=api_base,
                api_provider=llm_provider,
                requested_model=model_group,
                hashed_api_key=standard_logging_payload["metadata"][
                    "user_api_key_hash"
                ],
                api_key_alias=standard_logging_payload["metadata"][
                    "user_api_key_alias"
                ],
                team=standard_logging_payload["metadata"]["user_api_key_team_id"],
                team_alias=standard_logging_payload["metadata"][
                    "user_api_key_team_alias"
                ],
            ).inc()

            self.litellm_deployment_total_requests.labels(
                litellm_model_name=litellm_model_name,
                model_id=model_id,
                api_base=api_base,
                api_provider=llm_provider,
                requested_model=model_group,
                hashed_api_key=standard_logging_payload["metadata"][
                    "user_api_key_hash"
                ],
                api_key_alias=standard_logging_payload["metadata"][
                    "user_api_key_alias"
                ],
                team=standard_logging_payload["metadata"]["user_api_key_team_id"],
                team_alias=standard_logging_payload["metadata"][
                    "user_api_key_team_alias"
                ],
            ).inc()

            # Track deployment Latency
            response_ms: timedelta = end_time - start_time
            time_to_first_token_response_time: Optional[timedelta] = None

            if (
                request_kwargs.get("stream", None) is not None
                and request_kwargs["stream"] is True
            ):
                # only log ttft for streaming request
                time_to_first_token_response_time = (
                    request_kwargs.get("completion_start_time", end_time) - start_time
                )

            # use the metric that is not None
            # if streaming - use time_to_first_token_response
            # if not streaming - use response_ms
            _latency: timedelta = time_to_first_token_response_time or response_ms
            _latency_seconds = _latency.total_seconds()

            # latency per output token
            latency_per_token = None
            if output_tokens is not None and output_tokens > 0:
                latency_per_token = _latency_seconds / output_tokens
                _labels = prometheus_label_factory(
                    supported_enum_labels=PrometheusMetricLabels.get_labels(
                        label_name="litellm_deployment_latency_per_output_token"
                    ),
                    enum_values=enum_values,
                )
                self.litellm_deployment_latency_per_output_token.labels(
                    **_labels
                ).observe(latency_per_token)

        except Exception as e:
            verbose_logger.error(
                "Prometheus Error: set_llm_deployment_success_metrics. Exception occured - {}".format(
                    str(e)
                )
            )
            return

    async def log_success_fallback_event(
        self, original_model_group: str, kwargs: dict, original_exception: Exception
    ):
        """

        Logs a successful LLM fallback event on prometheus

        """
        from litellm.litellm_core_utils.litellm_logging import (
            StandardLoggingMetadata,
            StandardLoggingPayloadSetup,
        )

        verbose_logger.debug(
            "Prometheus: log_success_fallback_event, original_model_group: %s, kwargs: %s",
            original_model_group,
            kwargs,
        )
        _metadata = kwargs.get("metadata", {})
        standard_metadata: StandardLoggingMetadata = (
            StandardLoggingPayloadSetup.get_standard_logging_metadata(
                metadata=_metadata
            )
        )
        _new_model = kwargs.get("model")
        _tags = cast(List[str], kwargs.get("tags") or [])

        enum_values = UserAPIKeyLabelValues(
            requested_model=original_model_group,
            fallback_model=_new_model,
            hashed_api_key=standard_metadata["user_api_key_hash"],
            api_key_alias=standard_metadata["user_api_key_alias"],
            team=standard_metadata["user_api_key_team_id"],
            team_alias=standard_metadata["user_api_key_team_alias"],
            exception_status=str(getattr(original_exception, "status_code", None)),
            exception_class=str(original_exception.__class__.__name__),
            tags=_tags,
        )
        _labels = prometheus_label_factory(
            supported_enum_labels=PrometheusMetricLabels.get_labels(
                label_name="litellm_deployment_successful_fallbacks"
            ),
            enum_values=enum_values,
        )
        self.litellm_deployment_successful_fallbacks.labels(**_labels).inc()

    async def log_failure_fallback_event(
        self, original_model_group: str, kwargs: dict, original_exception: Exception
    ):
        """
        Logs a failed LLM fallback event on prometheus
        """
        from litellm.litellm_core_utils.litellm_logging import (
            StandardLoggingMetadata,
            StandardLoggingPayloadSetup,
        )

        verbose_logger.debug(
            "Prometheus: log_failure_fallback_event, original_model_group: %s, kwargs: %s",
            original_model_group,
            kwargs,
        )
        _new_model = kwargs.get("model")
        _metadata = kwargs.get("metadata", {})
        _tags = cast(List[str], kwargs.get("tags") or [])
        standard_metadata: StandardLoggingMetadata = (
            StandardLoggingPayloadSetup.get_standard_logging_metadata(
                metadata=_metadata
            )
        )

        enum_values = UserAPIKeyLabelValues(
            requested_model=original_model_group,
            fallback_model=_new_model,
            hashed_api_key=standard_metadata["user_api_key_hash"],
            api_key_alias=standard_metadata["user_api_key_alias"],
            team=standard_metadata["user_api_key_team_id"],
            team_alias=standard_metadata["user_api_key_team_alias"],
            exception_status=str(getattr(original_exception, "status_code", None)),
            exception_class=str(original_exception.__class__.__name__),
            tags=_tags,
        )

        _labels = prometheus_label_factory(
            supported_enum_labels=PrometheusMetricLabels.get_labels(
                label_name="litellm_deployment_failed_fallbacks"
            ),
            enum_values=enum_values,
        )
        self.litellm_deployment_failed_fallbacks.labels(**_labels).inc()

    def set_litellm_deployment_state(
        self,
        state: int,
        litellm_model_name: str,
        model_id: Optional[str],
        api_base: Optional[str],
        api_provider: str,
    ):
        self.litellm_deployment_state.labels(
            litellm_model_name, model_id, api_base, api_provider
        ).set(state)

    def set_deployment_healthy(
        self,
        litellm_model_name: str,
        model_id: str,
        api_base: str,
        api_provider: str,
    ):
        self.set_litellm_deployment_state(
            0, litellm_model_name, model_id, api_base, api_provider
        )

    def set_deployment_partial_outage(
        self,
        litellm_model_name: str,
        model_id: Optional[str],
        api_base: Optional[str],
        api_provider: str,
    ):
        self.set_litellm_deployment_state(
            1, litellm_model_name, model_id, api_base, api_provider
        )

    def set_deployment_complete_outage(
        self,
        litellm_model_name: str,
        model_id: Optional[str],
        api_base: Optional[str],
        api_provider: str,
    ):
        self.set_litellm_deployment_state(
            2, litellm_model_name, model_id, api_base, api_provider
        )

    def increment_deployment_cooled_down(
        self,
        litellm_model_name: str,
        model_id: str,
        api_base: str,
        api_provider: str,
        exception_status: str,
    ):
        """
        increment metric when litellm.Router / load balancing logic places a deployment in cool down
        """
        self.litellm_deployment_cooled_down.labels(
            litellm_model_name, model_id, api_base, api_provider, exception_status
        ).inc()

    def track_provider_remaining_budget(
        self, provider: str, spend: float, budget_limit: float
    ):
        """
        Track provider remaining budget in Prometheus
        """
        self.litellm_provider_remaining_budget_metric.labels(provider).set(
            self._safe_get_remaining_budget(
                max_budget=budget_limit,
                spend=spend,
            )
        )

    def _safe_get_remaining_budget(
        self, max_budget: Optional[float], spend: Optional[float]
    ) -> float:
        if max_budget is None:
            return float("inf")

        if spend is None:
            return max_budget

        return max_budget - spend

    def _initialize_prometheus_startup_metrics(self):
        """
        Initialize prometheus startup metrics

        Helper to create tasks for initializing metrics that are required on startup - eg. remaining budget metrics
        """
        if litellm.prometheus_initialize_budget_metrics is not True:
            verbose_logger.debug("Prometheus: skipping budget metrics initialization")
            return

        try:
            if asyncio.get_running_loop():
                asyncio.create_task(self._initialize_remaining_budget_metrics())
        except RuntimeError as e:  # no running event loop
            verbose_logger.exception(
                f"No running event loop - skipping budget metrics initialization: {str(e)}"
            )

    async def _initialize_budget_metrics(
        self,
        data_fetch_function: Callable[..., Awaitable[Tuple[List[Any], Optional[int]]]],
        set_metrics_function: Callable[[List[Any]], Awaitable[None]],
        data_type: Literal["teams", "keys"],
    ):
        """
        Generic method to initialize budget metrics for teams or API keys.

        Args:
            data_fetch_function: Function to fetch data with pagination.
            set_metrics_function: Function to set metrics for the fetched data.
            data_type: String representing the type of data ("teams" or "keys") for logging purposes.
        """
        from litellm.proxy.proxy_server import prisma_client

        if prisma_client is None:
            return

        try:
            page = 1
            page_size = 50
            data, total_count = await data_fetch_function(
                page_size=page_size, page=page
            )

            if total_count is None:
                total_count = len(data)

            # Calculate total pages needed
            total_pages = (total_count + page_size - 1) // page_size

            # Set metrics for first page of data
            await set_metrics_function(data)

            # Get and set metrics for remaining pages
            for page in range(2, total_pages + 1):
                data, _ = await data_fetch_function(page_size=page_size, page=page)
                await set_metrics_function(data)

        except Exception as e:
            verbose_logger.exception(
                f"Error initializing {data_type} budget metrics: {str(e)}"
            )

    async def _initialize_team_budget_metrics(self):
        """
        Initialize team budget metrics by reusing the generic pagination logic.
        """
        from litellm.proxy.management_endpoints.team_endpoints import (
            get_paginated_teams,
        )
        from litellm.proxy.proxy_server import prisma_client

        if prisma_client is None:
            verbose_logger.debug(
                "Prometheus: skipping team metrics initialization, DB not initialized"
            )
            return

        async def fetch_teams(
            page_size: int, page: int
        ) -> Tuple[List[LiteLLM_TeamTable], Optional[int]]:
            teams, total_count = await get_paginated_teams(
                prisma_client=prisma_client, page_size=page_size, page=page
            )
            if total_count is None:
                total_count = len(teams)
            return teams, total_count

        await self._initialize_budget_metrics(
            data_fetch_function=fetch_teams,
            set_metrics_function=self._set_team_list_budget_metrics,
            data_type="teams",
        )

    async def _initialize_api_key_budget_metrics(self):
        """
        Initialize API key budget metrics by reusing the generic pagination logic.
        """
        from typing import Union

        from litellm.constants import UI_SESSION_TOKEN_TEAM_ID
        from litellm.proxy.management_endpoints.key_management_endpoints import (
            _list_key_helper,
        )
        from litellm.proxy.proxy_server import prisma_client

        if prisma_client is None:
            verbose_logger.debug(
                "Prometheus: skipping key metrics initialization, DB not initialized"
            )
            return

        async def fetch_keys(
            page_size: int, page: int
        ) -> Tuple[List[Union[str, UserAPIKeyAuth]], Optional[int]]:
            key_list_response = await _list_key_helper(
                prisma_client=prisma_client,
                page=page,
                size=page_size,
                user_id=None,
                team_id=None,
                key_alias=None,
                exclude_team_id=UI_SESSION_TOKEN_TEAM_ID,
                return_full_object=True,
                organization_id=None,
            )
            keys = key_list_response.get("keys", [])
            total_count = key_list_response.get("total_count")
            if total_count is None:
                total_count = len(keys)
            return keys, total_count

        await self._initialize_budget_metrics(
            data_fetch_function=fetch_keys,
            set_metrics_function=self._set_key_list_budget_metrics,
            data_type="keys",
        )

    async def _initialize_remaining_budget_metrics(self):
        """
        Initialize remaining budget metrics for all teams to avoid metric discrepancies.

        Runs when prometheus logger starts up.
        """
        await self._initialize_team_budget_metrics()
        await self._initialize_api_key_budget_metrics()

    async def _set_key_list_budget_metrics(
        self, keys: List[Union[str, UserAPIKeyAuth]]
    ):
        """Helper function to set budget metrics for a list of keys"""
        for key in keys:
            if isinstance(key, UserAPIKeyAuth):
                self._set_key_budget_metrics(key)

    async def _set_team_list_budget_metrics(self, teams: List[LiteLLM_TeamTable]):
        """Helper function to set budget metrics for a list of teams"""
        for team in teams:
            self._set_team_budget_metrics(team)

    async def _set_team_budget_metrics_after_api_request(
        self,
        user_api_team: Optional[str],
        user_api_team_alias: Optional[str],
        team_spend: float,
        team_max_budget: float,
        response_cost: float,
    ):
        """
        Set team budget metrics after an LLM API request

        - Assemble a LiteLLM_TeamTable object
            - looks up team info from db if not available in metadata
        - Set team budget metrics
        """
        if user_api_team:
            team_object = await self._assemble_team_object(
                team_id=user_api_team,
                team_alias=user_api_team_alias or "",
                spend=team_spend,
                max_budget=team_max_budget,
                response_cost=response_cost,
            )

            self._set_team_budget_metrics(team_object)

    async def _assemble_team_object(
        self,
        team_id: str,
        team_alias: str,
        spend: Optional[float],
        max_budget: Optional[float],
        response_cost: float,
    ) -> LiteLLM_TeamTable:
        """
        Assemble a LiteLLM_TeamTable object

        for fields not available in metadata, we fetch from db
        Fields not available in metadata:
        - `budget_reset_at`
        """
        from litellm.proxy.auth.auth_checks import get_team_object
        from litellm.proxy.proxy_server import prisma_client, user_api_key_cache

        _total_team_spend = (spend or 0) + response_cost
        team_object = LiteLLM_TeamTable(
            team_id=team_id,
            team_alias=team_alias,
            spend=_total_team_spend,
            max_budget=max_budget,
        )
        try:
            team_info = await get_team_object(
                team_id=team_id,
                prisma_client=prisma_client,
                user_api_key_cache=user_api_key_cache,
            )
        except Exception as e:
            verbose_logger.debug(
                f"[Non-Blocking] Prometheus: Error getting team info: {str(e)}"
            )
            return team_object

        if team_info:
            team_object.budget_reset_at = team_info.budget_reset_at

        return team_object

    def _set_team_budget_metrics(
        self,
        team: LiteLLM_TeamTable,
    ):
        """
        Set team budget metrics for a single team

        - Remaining Budget
        - Max Budget
        - Budget Reset At
        """
        self.litellm_remaining_team_budget_metric.labels(
            team.team_id,
            team.team_alias or "",
        ).set(
            self._safe_get_remaining_budget(
                max_budget=team.max_budget,
                spend=team.spend,
            )
        )

        if team.max_budget is not None:
            self.litellm_team_max_budget_metric.labels(
                team.team_id,
                team.team_alias or "",
            ).set(team.max_budget)

        if team.budget_reset_at is not None:
            self.litellm_team_budget_remaining_hours_metric.labels(
                team.team_id,
                team.team_alias or "",
            ).set(
                self._get_remaining_hours_for_budget_reset(
                    budget_reset_at=team.budget_reset_at
                )
            )

    def _set_key_budget_metrics(self, user_api_key_dict: UserAPIKeyAuth):
        """
        Set virtual key budget metrics

        - Remaining Budget
        - Max Budget
        - Budget Reset At
        """
        enum_values = UserAPIKeyLabelValues(
            hashed_api_key=user_api_key_dict.token,
            api_key_alias=user_api_key_dict.key_alias or "",
        )
        _labels = prometheus_label_factory(
            supported_enum_labels=PrometheusMetricLabels.get_labels(
                label_name="litellm_remaining_api_key_budget_metric"
            ),
            enum_values=enum_values,
        )
        self.litellm_remaining_api_key_budget_metric.labels(**_labels).set(
            self._safe_get_remaining_budget(
                max_budget=user_api_key_dict.max_budget,
                spend=user_api_key_dict.spend,
            )
        )

        if user_api_key_dict.max_budget is not None:
            _labels = prometheus_label_factory(
                supported_enum_labels=PrometheusMetricLabels.get_labels(
                    label_name="litellm_api_key_max_budget_metric"
                ),
                enum_values=enum_values,
            )
            self.litellm_api_key_max_budget_metric.labels(**_labels).set(
                user_api_key_dict.max_budget
            )

        if user_api_key_dict.budget_reset_at is not None:
            self.litellm_api_key_budget_remaining_hours_metric.labels(**_labels).set(
                self._get_remaining_hours_for_budget_reset(
                    budget_reset_at=user_api_key_dict.budget_reset_at
                )
            )

    async def _set_api_key_budget_metrics_after_api_request(
        self,
        user_api_key: Optional[str],
        user_api_key_alias: Optional[str],
        response_cost: float,
        key_max_budget: float,
        key_spend: Optional[float],
    ):
        if user_api_key:
            user_api_key_dict = await self._assemble_key_object(
                user_api_key=user_api_key,
                user_api_key_alias=user_api_key_alias or "",
                key_max_budget=key_max_budget,
                key_spend=key_spend,
                response_cost=response_cost,
            )
            self._set_key_budget_metrics(user_api_key_dict)

    async def _assemble_key_object(
        self,
        user_api_key: str,
        user_api_key_alias: str,
        key_max_budget: float,
        key_spend: Optional[float],
        response_cost: float,
    ) -> UserAPIKeyAuth:
        """
        Assemble a UserAPIKeyAuth object
        """
        from litellm.proxy.auth.auth_checks import get_key_object
        from litellm.proxy.proxy_server import prisma_client, user_api_key_cache

        _total_key_spend = (key_spend or 0) + response_cost
        user_api_key_dict = UserAPIKeyAuth(
            token=user_api_key,
            key_alias=user_api_key_alias,
            max_budget=key_max_budget,
            spend=_total_key_spend,
        )
        try:
            if user_api_key_dict.token:
                key_object = await get_key_object(
                    hashed_token=user_api_key_dict.token,
                    prisma_client=prisma_client,
                    user_api_key_cache=user_api_key_cache,
                )
                if key_object:
                    user_api_key_dict.budget_reset_at = key_object.budget_reset_at
        except Exception as e:
            verbose_logger.debug(
                f"[Non-Blocking] Prometheus: Error getting key info: {str(e)}"
            )

        return user_api_key_dict

    def _get_remaining_hours_for_budget_reset(self, budget_reset_at: datetime) -> float:
        """
        Get remaining hours for budget reset
        """
        return (
            budget_reset_at - datetime.now(budget_reset_at.tzinfo)
        ).total_seconds() / 3600

    def _safe_duration_seconds(
        self,
        start_time: Any,
        end_time: Any,
    ) -> Optional[float]:
        """
        Compute the duration in seconds between two objects.

        Returns the duration as a float if both start and end are instances of datetime,
        otherwise returns None.
        """
        if isinstance(start_time, datetime) and isinstance(end_time, datetime):
            return (end_time - start_time).total_seconds()
        return None


def prometheus_label_factory(
    supported_enum_labels: List[str],
    enum_values: UserAPIKeyLabelValues,
    tag: Optional[str] = None,
) -> dict:
    """
    Returns a dictionary of label + values for prometheus.

    Ensures end_user param is not sent to prometheus if it is not supported.
    """
    # Extract dictionary from Pydantic object
    enum_dict = enum_values.model_dump()

    # Filter supported labels
    filtered_labels = {
        label: value
        for label, value in enum_dict.items()
        if label in supported_enum_labels
    }

    if UserAPIKeyLabelNames.END_USER.value in filtered_labels:
        filtered_labels["end_user"] = get_end_user_id_for_cost_tracking(
            litellm_params={"user_api_key_end_user_id": enum_values.end_user},
            service_type="prometheus",
        )

    if enum_values.custom_metadata_labels is not None:
        for key, value in enum_values.custom_metadata_labels.items():
            if key in supported_enum_labels:
                filtered_labels[key] = value

    for label in supported_enum_labels:
        if label not in filtered_labels:
            filtered_labels[label] = None

    return filtered_labels


def get_custom_labels_from_metadata(metadata: dict) -> Dict[str, str]:
    """
    Get custom labels from metadata
    """
    keys = litellm.custom_prometheus_metadata_labels
    if keys is None or len(keys) == 0:
        return {}

    result: Dict[str, str] = {}

    for key in keys:
        # Split the dot notation key into parts
        original_key = key
        key = key.replace("metadata.", "", 1) if key.startswith("metadata.") else key

        keys_parts = key.split(".")
        # Traverse through the dictionary using the parts
        value = metadata
        for part in keys_parts:
            value = value.get(part, None)  # Get the value, return None if not found
            if value is None:
                break

        if value is not None and isinstance(value, str):
            result[original_key.replace(".", "_")] = value

    return result
