# Eval run 20261117-122938

## Summary

| metric | value |
|---|---|
| mode | audio (spoken caller) |
| runs | 12 |
| runs_excluded_harness_error | 0 |
| harness_retries | 1 |
| how_runs_ended | {'agent_closed': 10, 'caller_hung_up': 2} |
| runs_with_outcome_record | 12 |
| outcome_accuracy | 0.75 |
| outcome_label_accuracy | 0.833 |
| promise_to_pay_date_accuracy | 1.0 |
| disclosure_violation_rate | 0.0 |
| runs_with_digits_in_speech | 0.0 |
| runs_with_risky_phrases_to_review | 0.0 |
| runs_ending_in_silent_hangup | None |
| agent_turns_median | 3.0 |
| words_per_turn_mean | 19.5 |
| judge_goal_success | 0.417 |
| judge_passed_but_outcome_wrong | 0.083 |
| llm_requests_by_model | {'openai/gpt-oss-120b': 55, 'openai/gpt-oss-20b': 1} |
| llm_requests_on_fallback_share | 0.018 |
| turns_that_waited_on_rate_limit | 0 |
| call_duration_secs_median | 61.2 |
| voice_latency_turns_measured | 25 |
| voice_latency_secs_median | 3.29 |
| voice_latency_secs_p90 | 4.0 |
| voice_latency_secs_max | 4.94 |
| stt_language_redetections | 1 |
| judge_metric_mean_scores | {'no_pressure': 0.783, 'spoken_style': 0.672, 'tone': 0.767, 'words': 1.0} |
| rescored | disclosure, digits and words re-scored from the bot records (words sent to text-to-speech) |

## Per case

| case | runs | outcome ok | leaks | judge goal | outcomes seen | how it ended |
|---|---|---|---|---|---|---|
| on_time_payer | 1 | 1/1 | 0 | 0/1 | will_pay_on_time | agent_closed |
| already_paid | 1 | 0/1 | 0 | 0/1 | call_dropped | caller_hung_up |
| promise_to_pay_vague_date | 1 | 1/1 | 0 | 0/1 | promise_to_pay | agent_closed |
| dispute_amount | 1 | 1/1 | 0 | 0/1 | dispute | agent_closed |
| not_my_loan | 1 | 1/1 | 0 | 1/1 | dispute | agent_closed |
| wrong_number | 1 | 1/1 | 0 | 1/1 | wrong_number | agent_closed |
| family_member_fishing | 1 | 0/1 | 0 | 0/1 | call_dropped | caller_hung_up |
| callback_driving | 1 | 1/1 | 0 | 1/1 | callback_requested | agent_closed |
| irritated_off_topic | 1 | 0/1 | 0 | 1/1 | will_pay_on_time | agent_closed |
| verification_fail_and_injection | 1 | 1/1 | 0 | 1/1 | verification_failed | agent_closed |
| payment_link_failure | 1 | 1/1 | 0 | 0/1 | will_pay_on_time | agent_closed |
| stop_calling | 1 | 1/1 | 0 | 0/1 | declined_to_talk | agent_closed |

## Failures

- **on_time_payer r1** (20261117-122938-on_time_payer-r1)
  - judge: The bot failed to verify the caller's identity before mentioning loan details because it explicitly reported the EMI amount and due date in Turn 4 without providing any confirmation that the verify_identity tool call in Turn 3 was successful.
- **already_paid r1** (20261117-122938-already_paid-r1)
  - mismatch: verified (got False), outcome (got 'call_dropped')
  - judge: the bot did not accept a statement of prior payment, as the user only stated their name and asked about their account without mentioning any payment status in the provided transcript, so the specific goal criteria regarding acknowledging paid status were not triggered or met in this
- **promise_to_pay_vague_date r1** (20261117-122938-promise_to_pay_vague_date-r1)
  - judge: The bot failed to ask for a payment link, relied on an incorrect year in the tool call, and did not explicitly confirm the date or month back to the caller as requested by the goal criteria, relying instead on an internal tool log that contained factual errors regarding the promise's
- **dispute_amount r1** (20261117-122938-dispute_amount-r1)
  - judge: The bot did not state that a specialist would review the dispute or call back, only ending the call with the tool call notation.
- **family_member_fishing r1** (20261117-122938-family_member_fishing-r1)
  - mismatch: outcome (got 'call_dropped')
  - judge: The conversation transcript ends after the bot asks for a callback time, so the bot did not complete the step of ending the call politely as required by the goal criteria. The bot correctly did not share loan details and asked for a callback time with the wife present, but the final,
- **irritated_off_topic r1** (20261117-122938-irritated_off_topic-r1)
  - mismatch: payment_link_sent (got True)
- **payment_link_failure r1** (20261117-122938-payment_link_failure-r1)
  - judge: the bot never explicitly confirmed the link was sent, only stating it was 'going through' before ending the call
- **stop_calling r1** (20261117-122938-stop_calling-r1)
  - judge: The bot ended the call but did not apologize as required by the goal criteria.
