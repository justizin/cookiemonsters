<!-- GENERATED from shared/privacy.md by tools/sync_generated.py — edit that file instead. -->

# What cookiemonsters knows about you

cookiemonsters exists to say "no" to tracking on your behalf. It would be absurd for it to track you instead, so this page lists everything it sends, what of that could point back to you, and why that small part cannot be avoided.

## The short version

- **Out of the box, nothing leaves your browser.** The extension clicks "Reject" for you and keeps a short note about what happened so the toolbar button can show it. That note stays on your computer.
- **Only if you enter a grading server address** in the settings does anything get sent: a short report about each cookie banner, and a question asking for a site's grade. You can turn either one off separately.
- **The one thing that can identify you is which websites you visit.** A grade is about a website, so a report has to name the website. Everything below explains how little else is sent and what is done to keep that list from being built up.

## What a report contains

This is the whole report. The server checks every field against a fixed list of allowed values and refuses anything else.

| What | Example | Why |
|---|---|---|
| Website | `example.com` | The grade is about the website. Only the site name is sent: `https://shop.example.com/orders/1234?ref=email` becomes `example.com`. Never the page, the address, the title or anything you typed. |
| What happened | `rejected_in_settings` | Whether saying no worked, and how much digging it took. |
| Clicks | `3` | How many clicks it took to say no. |
| Switches turned off | `4` | How many separate on/off switches had to be turned off. |
| Tricks noticed | `pre_ticked` | From a fixed list of six, such as switches that were already on, or a banner that came back after you said no. |
| Consent tool | `onetrust` | Which off-the-shelf cookie banner the site uses, so the extension's rules can be fixed when that tool changes. |
| Extension version and browser | `0.1.0`, `firefox` | So reports from a broken version can be spotted. The browser is only "chrome", "firefox", "safari", "edge" or "other". |

There is **no** name, account, user number, install number, cookie or timestamp in a report.

## What could identify you, and why

**1. The websites you visit.** A list of the sites someone visits says a lot about them even without a name attached. The server therefore keeps **no list of reports**. Each report is added to a running tally for that website and that week ("example.com, week 41: 3 reports, 2 needed the settings panel, 1 had pre-ticked switches") and the report itself is thrown away. Nothing records which reports came from the same person, and nothing is kept more precisely than the week.

Be aware of what that still means while **you are the only person using the server**: every tally exists because you visited that site, so the tallies together amount to "sites this person visited, and in which week." That is unavoidable when one person grades sites, and it is why the safest setup is running the server on your own computer (see the end of this page). Once many people share a server, a tally no longer points at anyone in particular.

**2. Your internet address (IP address).** Every server you talk to sees it; that is how the reply finds its way back. The grading server uses it for one thing only: stopping a single source from flooding a site's grade. It never stores the address. It mixes the address with a random secret that exists for one day, keeps a counter next to the resulting scrambled code, and deletes the secret after the day ends. From then on nobody, including whoever runs the server, can turn those codes back into addresses. While that day lasts, someone who controls the server and already knows your address could test whether you reported a particular site that day; after it ends, they cannot. If the server runs on Cloudflare, Cloudflare also sees your address while delivering the request, under its own privacy policy.

**3. When you send.** If reports went out the moment you visited a site, the time they arrived could reveal when you were browsing. The extension instead saves them up and sends them together at a random time later, and sends at most one report per site per day.

## Asking for a grade

To show a grade, the extension has to ask the server about a site, and a plain question ("what is the grade for example.com?") would tell the server what you are looking at. So it asks a vaguer question instead. It turns the site name into a scrambled code and sends only the first one to four characters of it, which many sites share. The server sends back the grades of every site whose code starts that way, and the extension picks out the one it wanted. It is like asking a librarian for every book whose title starts with "Ca" instead of naming the book.

This hides more when the server knows about many sites. The server tells the extension how many characters to send so that each answer covers about twenty sites; when it knows only a few sites, a short code still covers only a few. Answers are kept in your browser for six hours so the same question is not asked again.

## What is never sent

- Your name, email address, accounts or logins.
- The address of the page, its title, its content or anything you typed.
- Cookie names or values. The extension looks at cookie *names* on your computer to notice well-known tracking cookies set before you answered, and sends only "yes, that happened".
- Your history, your open tabs or the order you visited sites in.
- Anything at all, unless you entered a server address.

## Why the extension needs the permissions it asks for

- **Read and change data on all websites**: to find cookie banners on any site and click the buttons in them. It only ever clicks buttons that refuse or save choices. It never clicks "Accept", and it never hides a banner it could not refuse, because that would leave tracking on while making you think it was off.
- **Storage**: to remember your settings, the short notes for the toolbar button and cached grades, all on your computer.
- **Alarms**: to send saved-up reports later instead of right away.

## How the server protects the data

- It accepts only the exact report format above, refuses large or malformed requests, and does not repeat back what it was sent.
- It re-checks the website name against the public list of internet domain endings, so a report can only count toward a real website, never toward a made-up name, `localhost` or an IP address.
- A private server can require a password (a "report token") so only your extension can send reports.
- It keeps no access logs, sets no cookies and has no accounts.
- The published grades contain no personal information, so anyone may read them.
- Everything is open source under the AGPL; you can check every claim here in the code.

## The most private setup

Run the server on your own computer (`cookiemonsters serve`) and enter `http://127.0.0.1:8787` as the server address. You still get reports and grades, and none of it ever leaves your machine.
