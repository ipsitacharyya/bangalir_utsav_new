# বাঙালির উৎসব, বাঙালির গান

বাঙালীর দুর্গা পূজার ভার্চুয়াল সঙ্গী। শুনুন রেডিও, পুজোর গান, ভার্চুয়াল পুজো আড্ডা আরও অনেক কিছু।

🌸 আপনার দুর্গাপুজোকে আরও আনন্দময় করে তুলুন!

* The full homepage is rendered in one long page instead of swapping out the rest of the page when one media section is selected.
* Main navigation uses same-tab `#hash` links with `target="\_self"`. Clicking Puja Songs / Pujo TV / Live Radio / Puja Sound scrolls to the real functional player section in the same tab.
* The top and secondary Mahalaya countdowns are Bengali and use the existing Noto Serif Bengali Google font.
* The content container is widened so large screens use the page width instead of leaving excessive side whitespace.
* Small Bengali-style alpana corner ornaments were added as a lightweight SVG: `assets/decorations/alpana\_corner.svg`.
* The footer uses `footer\_diya.PNG` mirrored on the left and `footer\_dhak.PNG` on the right so the two side images balance symmetrically.
* The retro players keep their existing controls and behavior, with their outer palette aligned to the page's maroon / brass / cream visual language.
* Puja Sound remains safe with an empty `assets/sounds/` directory. Adding the sound files later does not require changing the page structure.

## Run locally

```bash
python -m pip install -r requirements.txt
streamlit run main.py
```

For local secrets, copy:

```text
.streamlit/secrets.toml.example
```

to:

```text
.streamlit/secrets.toml
```

and put your real values there.

## Secret handling

Never commit the real `.streamlit/secrets.production.toml` to GitHub. It is ignored by `.gitignore`. The repository should contain only `.streamlit/secrets.toml.example` as a safe template.

For Streamlit Community Cloud, add the real secrets in the app's **Secrets** settings instead of committing them to the repository.

## Existing integrations

Supabase, the Google Apps Script song-request webhook, Pushpanjali counter, location board, radio streams, gallery and admin analytics remain in the existing architecture.

The six Puja Sound filenames expected by the later audio implementation are:

```text
assets/sounds/dhak.mp3
assets/sounds/kansar.mp3
assets/sounds/bell.mp3
assets/sounds/chanting.mp3
assets/sounds/fireworks.mp3
assets/sounds/crowd.mp3
```

The sound folder may remain empty while the website is being designed.



Test Database: test@bangalirutsav123

