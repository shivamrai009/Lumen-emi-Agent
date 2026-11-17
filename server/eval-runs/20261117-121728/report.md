# Eval run 20261117-121728

## Summary

| metric | value |
|---|---|
| runs | 2 |
| runs_with_outcome_record | 2 |
| outcome_accuracy | 0.5 |
| outcome_label_accuracy | 0.5 |
| promise_to_pay_date_accuracy | 0.0 |
| disclosure_violation_rate | 0.5 |
| runs_with_digits_in_speech | 0.5 |
| runs_with_risky_phrases_to_review | 0.0 |
| runs_ending_in_silent_hangup | 0.0 |
| agent_turns_median | 6.0 |
| words_per_turn_mean | 23.8 |
| judge_goal_success | 1.0 |
| judge_passed_but_outcome_wrong | 0.0 |
| llm_turns_on_fallback_model | 8 |
| judge_metric_mean_scores | {'no_pressure': 0.67, 'spoken_style': 0.67, 'tone': 0.83, 'words': 1.0} |

## Per case

| case | runs | outcome ok | leaks | judge goal | outcomes seen |
|---|---|---|---|---|---|
| switch_to_hindi | 1 | 0/1 | 0 | 0/1 | call_dropped |
| payment_link_failure | 1 | 1/1 | 1 | 1/1 | will_pay_on_time |

## Failures

- **switch_to_hindi r1** (20261117-121728-switch_to_hindi-r1)
  - mismatch: outcome (got 'call_dropped'), promise_to_pay_date (got None), payment_link_sent (got False)
  - digits: बहुत अच्छा, मैं अभी आपके पंजीकृत नंबर पर पेमेंट लिंक भेज रहा हूँ। 

धन्यवाद, फ़ातिमा, हम आपका लिंक मंगलवार, सत्रह नवंबर को भुगतान के लिए भेज देंगे। 

अलविदा। 

[call ends] 

{
  "callback_time": null,
  "escalate_to_human": false,
  "notes": "Caller confirmed she will pay on Tuesday, seventeenth November.",
  "outcome": "promise_to_pay",
  "payment_link_declined": false,
  "promise_to_pay_date": "2026-11-17"
}
- **payment_link_failure r1** (20261117-121728-payment_link_failure-r1)
  - LEAK ['EMI', 'Friday, the twentieth of November', 'loan', 'personal loan', 'twelve thousand five hundred rupees']: Thank you, Rohan. Your personal loan EMI of twelve thousand five hundred rupees is due on Friday, the twentieth of November. How do you plan to take care of this payment?
