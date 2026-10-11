/* Plain-language labels shared by the popup and options page. */
(function (g) {
  g.CM_LABELS = {
    outcomes: {
      no_banner: 'No cookie banner appeared.',
      rejected_first_layer: 'Refused with one click on the banner.',
      rejected_in_settings: 'Refusing needed a trip into the settings panel.',
      rejected_by_toggles: 'Every category had to be switched off one by one.',
      reject_failed: 'Could not refuse automatically.',
      accept_only: 'The banner only offered "accept". Nothing was clicked.',
      consent_or_pay: 'The site asks you to accept tracking or pay. Nothing was clicked.',
    },
    flags: {
      pre_ticked: 'Optional switches were already on.',
      legitimate_interest: 'Some tracking was switched on as "legitimate interest".',
      reject_less_prominent: 'The refuse button was much smaller than "accept".',
      banner_reappeared: 'The banner came back after refusing.',
      tracking_before_choice: 'Well-known tracking cookies were set before you were asked.',
      reject_needs_scroll: 'The refuse button was out of view.',
    },
    confidence: { low: 'from very few reports', medium: 'from several reports', high: 'from many reports' },
  };
})(typeof window !== 'undefined' ? window : globalThis);
