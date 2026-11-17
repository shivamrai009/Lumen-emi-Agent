# Eval run 20261117-122442

## Summary

| metric | value |
|---|---|
| mode | audio (spoken caller) |
| runs | 1 |
| runs_excluded_harness_error | 0 |
| harness_retries | 0 |
| how_runs_ended | {'agent_closed': 1} |
| runs_with_outcome_record | 1 |
| outcome_accuracy | 1.0 |
| outcome_label_accuracy | 1.0 |
| promise_to_pay_date_accuracy | None |
| disclosure_violation_rate | 0.0 |
| runs_with_digits_in_speech | 1.0 |
| runs_with_risky_phrases_to_review | 0.0 |
| runs_ending_in_silent_hangup | 0.0 |
| agent_turns_median | 4 |
| words_per_turn_mean | 17.8 |
| judge_goal_success | 0.0 |
| judge_passed_but_outcome_wrong | 0.0 |
| llm_requests_by_model | {'openai/gpt-oss-120b': 6} |
| llm_requests_on_fallback_share | 0.0 |
| turns_that_waited_on_rate_limit | 0 |
| call_duration_secs_median | 69.0 |
| voice_latency_turns_measured | 3 |
| voice_latency_secs_median | 5.55 |
| voice_latency_secs_p90 | 6.31 |
| voice_latency_secs_max | 6.5 |
| stt_language_redetections | 0 |
| judge_metric_mean_scores | {'no_pressure': 0.5, 'spoken_style': 0.25, 'tone': 0.5, 'words': 1.0} |

## Per case

| case | runs | outcome ok | leaks | judge goal | outcomes seen | how it ended |
|---|---|---|---|---|---|---|
| on_time_payer | 1 | 1/1 | 0 | 0/1 | will_pay_on_time | agent_closed |

## Failures

- **on_time_payer r1** (20261117-122442-on_time_payer-r1)
  - digits: Thank you, Rohan. Your personal loan, Emi, of 12,500 rupees is due on Friday, the twentieth of November. How would you like? Would you like to proceed with the payment?
  - judge: P(yes)=0.25
