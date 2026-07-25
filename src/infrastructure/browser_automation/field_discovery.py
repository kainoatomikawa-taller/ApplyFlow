"""Form-field discovery — the single in-page pass that turns whatever HTML
a portal served into `FormField` descriptions.

All of the DOM work happens in one `evaluate()` per frame rather than as
per-field Playwright round trips. That is not only faster on forms with
sixty questions: it also means every field is read from one consistent
view of the DOM, so a page mutating mid-read cannot produce a snapshot
that mixes two different versions of the form.

What is deliberately NOT discovered here:

- **Hidden, disabled, read-only, and button-ish controls.** They are not
  fillable, and exposing them would hand a caller a way to press things —
  including submit. Nothing this harness returns can submit an
  application.
- **Custom widgets built out of divs.** Several large ATS platforms hide
  the native `<select>` and paint their own combobox; the hidden native
  element fails the visibility check and drops out. That is correct
  behavior for this layer (Playwright would refuse to interact with it
  anyway) and the reason custom-widget support is its own capability
  rather than a special case bolted onto field discovery.

Visibility is judged by Playwright's own definition — non-empty bounding
box, `visibility` not `hidden` — precisely so that everything reported as
fillable is something Playwright will actually agree to interact with.
"""

from __future__ import annotations

from typing import Any

from src.application.ports.browser_automation_port import (
    FormField,
    FormFieldKind,
    FormFieldOption,
)

#: The CSS selector field handles are resolved against. The in-page pass
#: below MUST enumerate exactly this selector, in document order, because a
#: handle's index is its position in that enumeration.
FIELD_SELECTOR = "input, textarea, select"

#: Normalized `<input type>` (as reported by `el.type`, which already
#: collapses unknown types to "text") → the kind a caller branches on.
_INPUT_TYPE_KINDS: dict[str, FormFieldKind] = {
    "text": FormFieldKind.TEXT,
    "search": FormFieldKind.TEXT,
    "password": FormFieldKind.PASSWORD,
    "email": FormFieldKind.EMAIL,
    "tel": FormFieldKind.PHONE,
    "url": FormFieldKind.URL,
    "number": FormFieldKind.NUMBER,
    "range": FormFieldKind.NUMBER,
    "date": FormFieldKind.DATE,
    "month": FormFieldKind.DATE,
    "week": FormFieldKind.DATE,
    "time": FormFieldKind.DATE,
    "datetime-local": FormFieldKind.DATE,
    "checkbox": FormFieldKind.CHECKBOX,
    "radio": FormFieldKind.RADIO,
    "file": FormFieldKind.FILE,
}

#: Evaluated in each frame; returns one entry per fillable field, carrying
#: its index in `FIELD_SELECTOR`'s document-order enumeration.
FIELD_DISCOVERY_JS = """
() => {
  const SELECTOR = 'input, textarea, select';
  const SKIPPED_INPUT_TYPES = new Set(['hidden', 'submit', 'button', 'reset', 'image']);
  const ATTRIBUTES_OF_INTEREST = [
    'id', 'type', 'autocomplete', 'inputmode', 'pattern', 'aria-describedby',
  ];
  const MAX_LABEL_LENGTH = 300;

  const clean = (text) =>
    (text || '').replace(/\\s+/g, ' ').trim().slice(0, MAX_LABEL_LENGTH);

  const isVisible = (el) => {
    const style = el.ownerDocument.defaultView.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const fromAriaLabelledBy = (el) => {
    const raw = el.getAttribute('aria-labelledby') || '';
    const ids = raw.split(/\\s+/).filter(Boolean);
    if (ids.length === 0) return '';
    const parts = ids.map((id) => {
      const target = el.ownerDocument.getElementById(id);
      return target ? target.textContent : '';
    });
    return clean(parts.join(' '));
  };

  const fromNativeLabels = (el) => {
    const labels = el.labels ? Array.from(el.labels) : [];
    for (const label of labels) {
      const text = clean(label.textContent);
      if (text) return text;
    }
    return '';
  };

  const fromWrappingLabel = (el) => {
    const label = el.closest('label');
    return label ? clean(label.textContent) : '';
  };

  const labelFor = (el) =>
    clean(el.getAttribute('aria-label'))
    || fromAriaLabelledBy(el)
    || fromNativeLabels(el)
    || fromWrappingLabel(el)
    || clean(el.getAttribute('placeholder'))
    || clean(el.getAttribute('name'))
    || clean(el.getAttribute('id'));

  const isRequired = (el) =>
    el.required === true || el.getAttribute('aria-required') === 'true';

  const asText = (value) =>
    value === null || value === undefined ? '' : String(value);

  const optionsFor = (el) =>
    Array.from(el.options || []).map((option) => ({
      label: clean(option.label || option.textContent),
      value: asText(option.value),
    }));

  const fields = [];
  const found = document.querySelectorAll(SELECTOR);
  for (let index = 0; index < found.length; index += 1) {
    const el = found[index];
    const tag = el.tagName.toLowerCase();
    const type = tag === 'input' ? String(el.type || 'text').toLowerCase() : tag;
    if (tag === 'input' && SKIPPED_INPUT_TYPES.has(type)) continue;
    if (el.disabled === true || el.readOnly === true) continue;
    if (!isVisible(el)) continue;

    const attributes = {};
    for (const name of ATTRIBUTES_OF_INTEREST) {
      const value = el.getAttribute(name);
      if (value !== null && value !== '') attributes[name] = clean(value);
    }

    const name = el.getAttribute('name') || '';
    const id = el.getAttribute('id') || '';
    const checkable = type === 'checkbox' || type === 'radio';
    const value = asText(el.value);

    fields.push({
      index,
      tag,
      type,
      name,
      label: labelFor(el),
      required: isRequired(el),
      placeholder: clean(el.getAttribute('placeholder')),
      value,
      attributes,
      checked: checkable ? el.checked === true : false,
      options: tag === 'select' ? optionsFor(el) : [],
      maxLength: typeof el.maxLength === 'number' && el.maxLength > 0
        ? el.maxLength
        : null,
      signature: [tag, type, name, id, checkable ? value : ''].join('|'),
    });
  }
  return fields;
}
"""


#: Evaluated against a single element to re-derive the `signature` the
#: discovery pass recorded for it. MUST stay byte-for-byte equivalent to
#: the `signature` expression above — the two are compared to detect a
#: handle that has drifted onto a different field, so a divergence between
#: them would either raise constantly or, worse, stop catching drift.
#:
#: Notably excludes the value of anything that isn't a checkbox/radio,
#: since filling a text field changes its value and a signature that moved
#: when written to could never be verified twice.
FIELD_SIGNATURE_JS = """
(el) => {
  const tag = el.tagName.toLowerCase();
  const type = tag === 'input' ? String(el.type || 'text').toLowerCase() : tag;
  const name = el.getAttribute('name') || '';
  const id = el.getAttribute('id') || '';
  const checkable = type === 'checkbox' || type === 'radio';
  const value = el.value === null || el.value === undefined ? '' : String(el.value);
  return [tag, type, name, id, checkable ? value : ''].join('|');
}
"""


def field_kind(tag: str, input_type: str) -> FormFieldKind:
    """Map a discovered element's tag/type onto the kind callers branch on."""
    if tag == "textarea":
        return FormFieldKind.TEXTAREA
    if tag == "select":
        return FormFieldKind.SELECT
    return _INPUT_TYPE_KINDS.get(input_type, FormFieldKind.TEXT)


def to_form_field(handle: str, raw: dict[str, Any]) -> FormField:
    """Build a `FormField` from one in-page discovery entry.

    Defensive about the payload's shape rather than trusting it: it comes
    from JavaScript running against a page the portal controls, so every
    value is coerced to the type this side promises.
    """
    tag = str(raw.get("tag", ""))
    input_type = str(raw.get("type", ""))
    options = tuple(
        FormFieldOption(
            label=str(option.get("label", "")), value=str(option.get("value", ""))
        )
        for option in raw.get("options") or ()
        if isinstance(option, dict)
    )
    max_length = raw.get("maxLength")
    attributes = {
        str(key): str(value) for key, value in (raw.get("attributes") or {}).items()
    }
    return FormField(
        handle=handle,
        kind=field_kind(tag, input_type),
        label=str(raw.get("label", "")),
        name=str(raw.get("name", "")),
        required=bool(raw.get("required", False)),
        placeholder=str(raw.get("placeholder", "")),
        value=str(raw.get("value", "")),
        checked=bool(raw.get("checked", False)),
        options=options,
        max_length=int(max_length) if isinstance(max_length, int | float) else None,
        attributes=attributes,
    )
