# Eval run 20261117-125858

## Summary

| metric | value |
|---|---|
| mode | audio (spoken caller) |
| runs | 2 |
| runs_excluded_harness_error | 1 |
| harness_retries | 2 |
| how_runs_ended | {'caller_hung_up': 1, 'agent_closed': 1} |
| runs_with_outcome_record | 2 |
| outcome_accuracy | 1.0 |
| outcome_label_accuracy | 1.0 |
| promise_to_pay_date_accuracy | None |
| disclosure_violation_rate | 0.0 |
| runs_with_digits_in_speech | 0.0 |
| runs_with_risky_phrases_to_review | 0.0 |
| runs_ending_in_silent_hangup | None |
| agent_turns_median | 3.5 |
| words_per_turn_mean | 22.8 |
| judge_goal_success | 0.0 |
| judge_passed_but_outcome_wrong | 0.0 |
| llm_requests_by_model | {'openai/gpt-oss-120b': 2, 'openai/gpt-oss-20b': 10} |
| llm_requests_on_fallback_share | 0.833 |
| turns_that_waited_on_rate_limit | 0 |
| call_duration_secs_median | 72.6 |
| voice_latency_turns_measured | 6 |
| voice_latency_secs_median | 3.23 |
| voice_latency_secs_p90 | 4.23 |
| voice_latency_secs_max | 4.3 |
| stt_language_redetections | 0 |
| judge_metric_mean_scores | {'no_pressure': 0.4, 'spoken_style': 0.4, 'tone': 0.4, 'words': 1.0} |
| rescored | disclosure, digits and words re-scored from the bot records (words sent to text-to-speech) |

## Per case

| case | runs | outcome ok | leaks | judge goal | outcomes seen | how it ended |
|---|---|---|---|---|---|---|
| already_paid | 1 | 1/1 | 0 | 0/1 | paid_already | caller_hung_up |
| family_member_fishing | 1 | 1/1 | 0 | 0/1 | callback_requested | agent_closed |
| irritated_off_topic | 1 | 0/1 | 0 | 0/1 | call_dropped | harness_error |

## Failures

- **already_paid r1** (20261117-125858-already_paid-r1)
  - judge: The bot asked the user to share proof of the UPI transaction, which contradicts the goal requirement to accept the payment without arguing or asking for proof or demonstration that it may take time to reflect, the bot did not explicitly state the delay period and its demand for proof
- **irritated_off_topic r1** (20261117-125858-irritated_off_topic-r1)
  - harness error after retries (excluded from the rates above)
  - mismatch: verified (got False), outcome (got 'call_dropped')
