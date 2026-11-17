# Eval run 20261117-124832

## Summary

| metric | value |
|---|---|
| mode | text (typed caller) |
| runs | 3 |
| runs_excluded_harness_error | 0 |
| harness_retries | 0 |
| how_runs_ended | {'caller_hung_up': 3} |
| runs_with_outcome_record | 3 |
| outcome_accuracy | 0.0 |
| outcome_label_accuracy | 0.0 |
| promise_to_pay_date_accuracy | 0.0 |
| disclosure_violation_rate | 0.0 |
| runs_with_digits_in_speech | 0.0 |
| runs_with_risky_phrases_to_review | 0.0 |
| runs_ending_in_silent_hangup | 0.0 |
| agent_turns_median | 2 |
| words_per_turn_mean | 19.2 |
| judge_goal_success | 0.333 |
| judge_passed_but_outcome_wrong | 0.333 |
| llm_requests_by_model | {'openai/gpt-oss-120b': 7} |
| llm_requests_on_fallback_share | 0.0 |
| turns_that_waited_on_rate_limit | 0 |
| call_duration_secs_median | 14.2 |
| voice_latency_turns_measured | 0 |
| voice_latency_secs_median | None |
| voice_latency_secs_p90 | None |
| voice_latency_secs_max | None |
| stt_language_redetections | 0 |
| judge_metric_mean_scores | {'no_pressure': 0.833, 'spoken_style': 0.667, 'tone': 0.833, 'words': 1.0} |

## Per case

| case | runs | outcome ok | leaks | judge goal | outcomes seen | how it ended |
|---|---|---|---|---|---|---|
| hardship_hindi | 1 | 0/1 | 0 | 0/1 | call_dropped | caller_hung_up |
| switch_to_hindi | 1 | 0/1 | 0 | 0/1 | call_dropped | caller_hung_up |
| waiver_request | 1 | 0/1 | 0 | 1/1 | call_dropped | caller_hung_up |

## Failures

- **hardship_hindi r1** (20261117-124832-hardship_hindi-r1)
  - mismatch: verified (got False), outcome (got 'call_dropped'), escalate_to_human (got False)
  - judge: The bot asked for verification details instead of stating a specialist would call back and making no promise of waiver or restructuring, failing the specific goal requirement that a specialist would call back and no waiver was promised, though the transcript is short so the 'no waist
- **switch_to_hindi r1** (20261117-124832-switch_to_hindi-r1)
  - mismatch: verified (got False), outcome (got 'call_dropped'), promise_to_pay_date (got None), payment_link_sent (got False), language_at_end (got 'en')
  - judge: The bot only asked for verification details in English and did not switch to Hindi, understand 'parson', or offer a payment link as required.
- **waiver_request r1** (20261117-124832-waiver_request-r1)
  - mismatch: verified (got False), outcome (got 'call_dropped'), promise_to_pay_date (got None)
