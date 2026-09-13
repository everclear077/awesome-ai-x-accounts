## Account or change

- X profile URL:
- Numeric X account ID:
- Category:
- Observation time (with timezone):
- Old handle, if this is a rename:

Copy the profile bio exactly. Provide the observed follower count without estimating
from rounded numbers. A recommendation or follower threshold is not required.

Guides: [English](https://github.com/everclear077/awesome-ai-x-accounts/blob/main/CONTRIBUTING.md) · [中文](https://github.com/everclear077/awesome-ai-x-accounts/blob/main/CONTRIBUTING.zh-CN.md) · [한국어](https://github.com/everclear077/awesome-ai-x-accounts/blob/main/CONTRIBUTING.ko.md) · [日本語](https://github.com/everclear077/awesome-ai-x-accounts/blob/main/CONTRIBUTING.ja.md) · [Русский](https://github.com/everclear077/awesome-ai-x-accounts/blob/main/CONTRIBUTING.ru.md) · [Français](https://github.com/everclear077/awesome-ai-x-accounts/blob/main/CONTRIBUTING.fr.md) · [Español](https://github.com/everclear077/awesome-ai-x-accounts/blob/main/CONTRIBUTING.es.md)

## Checklist

- [ ] Checked duplicate handles and numeric account IDs
- [ ] Copied the original bio, with no editorial description or translation
- [ ] Recorded exact followers (or null), actual observation time, and profile retrieval URL
- [ ] Edited source data and regenerated all seven README editions
- [ ] Removed the pending queue entry if applicable
- [ ] `python scripts/catalog.py check`
- [ ] `python -m unittest discover -s tests -v`
- [ ] `git diff --check`
- [ ] Reviewed the changed account rows and navigation

## Additional context

For interface or code changes, describe the resulting behavior and checks performed.
For missing profile fields, explain what could not be retrieved.

Main requires current Catalog checks and resolved conversations. Merge through the
PR without bypassing protection.
