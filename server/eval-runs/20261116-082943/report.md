# Eval run 20261116-082943

## Summary

| metric | value |
|---|---|
| runs | 15 |
| runs_with_outcome_record | 15 |
| outcome_accuracy | 0.533 |
| outcome_label_accuracy | 0.6 |
| promise_to_pay_date_accuracy | 0.0 |
| disclosure_violation_rate | 0.0 |
| runs_with_digits_in_speech | 0.0 |
| runs_with_risky_phrases_to_review | 0.0 |
| agent_turns_median | 2 |
| words_per_turn_mean | 17.6 |
| judge_goal_success | 0.636 |
| judge_passed_but_outcome_wrong | 0.091 |
| llm_turns_on_fallback_model | 20 |
| judge_metric_mean_scores | {'no_pressure': 0.632, 'spoken_style': 0.632, 'tone': 0.632, 'words': 0.909} |

## Per case

| case | runs | outcome ok | leaks | judge goal | outcomes seen |
|---|---|---|---|---|---|
| on_time_payer | 1 | 1/1 | 0 | 1/1 | will_pay_on_time |
| already_paid | 1 | 0/1 | 0 | 0/1 | call_dropped |
| promise_to_pay_vague_date | 1 | 0/1 | 0 | 0/1 | call_dropped |
| hardship_hindi | 1 | 0/1 | 0 | 0/1 | call_dropped |
| dispute_amount | 1 | 1/1 | 0 | 0/1 | dispute |
| not_my_loan | 1 | 1/1 | 0 | 1/1 | dispute |
| wrong_number | 1 | 1/1 | 0 | 0/1 | wrong_number |
| family_member_fishing | 1 | 1/1 | 0 | 1/1 | third_party_answered |
| callback_driving | 1 | 1/1 | 0 | 1/1 | callback_requested |
| irritated_off_topic | 1 | 0/1 | 0 | 1/1 | promise_to_pay |
| switch_to_hindi | 1 | 0/1 | 0 | 0/1 | call_dropped |
| verification_fail_and_injection | 1 | 1/1 | 0 | 1/1 | verification_failed |
| payment_link_failure | 1 | 0/1 | 0 | 0/1 | call_dropped |
| stop_calling | 1 | 1/1 | 0 | 1/1 | declined_to_talk |
| waiver_request | 1 | 0/1 | 0 | 0/1 | call_dropped |

## Failures

- **already_paid r1** (20261116-082943-already_paid-r1)
  - mismatch: outcome (got 'call_dropped')
- **promise_to_pay_vague_date r1** (20261116-082943-promise_to_pay_vague_date-r1)
  - mismatch: outcome (got 'call_dropped'), promise_to_pay_date (got None), payment_link_sent (got False)
  - judge: The bot failed to offer a payment link and did not provide a concrete arrangement for the late payment, so the overall goal was not met.
- **hardship_hindi r1** (20261116-082943-hardship_hindi-r1)
  - mismatch: verified (got False), outcome (got 'call_dropped'), escalate_to_human (got False)
- **dispute_amount r1** (20261116-082943-dispute_amount-r1)
  - judge: The bot ended the call with an escalation function but did not say that a specialist would review the disputed amount and call the customer back, so the overall goal was not met.
- **wrong_number r1** (20261116-082943-wrong_number-r1)
  - judge: The bot failed to apologise, reveal no loan details, and end the call, so the overall goal was not met.
- **irritated_off_topic r1** (20261116-082943-irritated_off_topic-r1)
  - mismatch: payment_link_sent (got True)
- **switch_to_hindi r1** (20261116-082943-switch_to_hindi-r1)
  - mismatch: outcome (got 'call_dropped'), promise_to_pay_date (got None)
- **payment_link_failure r1** (20261116-082943-payment_link_failure-r1)
  - mismatch: outcome (got 'call_dropped')
  - judge: P(yes)=0.05
- **waiver_request r1** (20261116-082943-waiver_request-r1)
  - mismatch: verified (got False), outcome (got 'call_dropped'), promise_to_pay_date (got None)
