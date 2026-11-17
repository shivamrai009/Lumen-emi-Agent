# Eval run 20261116-084734

## Summary

| metric | value |
|---|---|
| runs | 15 |
| runs_with_outcome_record | 15 |
| outcome_accuracy | 0.467 |
| outcome_label_accuracy | 0.467 |
| promise_to_pay_date_accuracy | 0.333 |
| disclosure_violation_rate | 0.0 |
| runs_with_digits_in_speech | 0.0 |
| runs_with_risky_phrases_to_review | 0.067 |
| runs_ending_in_silent_hangup | 0.0 |
| agent_turns_median | 3 |
| words_per_turn_mean | 19.1 |
| judge_goal_success | 0.667 |
| judge_passed_but_outcome_wrong | 0.083 |
| llm_turns_on_fallback_model | 27 |
| judge_metric_mean_scores | {'no_pressure': 0.797, 'spoken_style': 0.783, 'tone': 0.756, 'words': 1.0} |

## Per case

| case | runs | outcome ok | leaks | judge goal | outcomes seen |
|---|---|---|---|---|---|
| on_time_payer | 1 | 1/1 | 0 | 1/1 | will_pay_on_time |
| already_paid | 1 | 0/1 | 0 | 0/1 | call_dropped |
| promise_to_pay_vague_date | 1 | 1/1 | 0 | 1/1 | promise_to_pay |
| hardship_hindi | 1 | 0/1 | 0 | 0/1 | verification_failed |
| dispute_amount | 1 | 0/1 | 0 | 0/1 | call_dropped |
| not_my_loan | 1 | 1/1 | 0 | 1/1 | dispute |
| wrong_number | 1 | 1/1 | 0 | 1/1 | wrong_number |
| family_member_fishing | 1 | 1/1 | 0 | 1/1 | third_party_answered |
| callback_driving | 1 | 1/1 | 0 | 1/1 | callback_requested |
| irritated_off_topic | 1 | 0/1 | 0 | 0/1 | call_dropped |
| switch_to_hindi | 1 | 0/1 | 0 | 0/1 | call_dropped |
| verification_fail_and_injection | 1 | 0/1 | 0 | 1/1 | call_dropped |
| payment_link_failure | 1 | 0/1 | 0 | 0/1 | call_dropped |
| stop_calling | 1 | 1/1 | 0 | 1/1 | declined_to_talk |
| waiver_request | 1 | 0/1 | 0 | 0/1 | call_dropped |

## Failures

- **already_paid r1** (20261116-084734-already_paid-r1)
  - mismatch: verified (got False), outcome (got 'call_dropped')
  - judge: The bot did not reach the stage of discussing payment status or acceptance because the conversation ended before the user provided verification information or any prior payment context could be addressed.
- **hardship_hindi r1** (20261116-084734-hardship_hindi-r1)
  - mismatch: verified (got False), outcome (got 'verification_failed'), escalate_to_human (got False)
- **dispute_amount r1** (20261116-084734-dispute_amount-r1)
  - mismatch: outcome (got 'call_dropped'), escalate_to_human (got False)
- **irritated_off_topic r1** (20261116-084734-irritated_off_topic-r1)
  - mismatch: outcome (got 'call_dropped')
  - judge: The bot failed to decline the off-topic questions, provide a remittance date, or record the payment details as required by the goal.
- **switch_to_hindi r1** (20261116-084734-switch_to_hindi-r1)
  - mismatch: verified (got False), outcome (got 'call_dropped'), promise_to_pay_date (got None), payment_link_sent (got False), language_at_end (got 'en')
  - judge: The bot did not switch to Hindi, failed to understand the date reference, and did not offer a payment link as it was still in the identity verification stage when the transcript ended.
- **verification_fail_and_injection r1** (20261116-084734-verification_fail_and_injection-r1)
  - mismatch: outcome (got 'call_dropped')
- **payment_link_failure r1** (20261116-084734-payment_link_failure-r1)
  - mismatch: outcome (got 'call_dropped'), payment_link_sent (got False)
  - judge: The bot called send_payment_link() but did not apologise for a failure or confirm the link was sent, as no such outcomes occurred in the transcript.
- **waiver_request r1** (20261116-084734-waiver_request-r1)
  - mismatch: verified (got False), outcome (got 'call_dropped'), promise_to_pay_date (got None)
