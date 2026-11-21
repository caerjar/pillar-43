# Synthetic press archive: Lantern Wharf Editions

A fully invented small-press drive for testing an offline archive app. Every press, person, title, ISBN, date, place and text is invented. No real press, author or published text is used. Rebuild with `python3 fixtures/make_synthetic_press.py` (seeded, standard library only; recordings need macOS `say` and `afconvert`).

## The press
Lantern Wharf Editions is a small poetry and translation press at 3 Tallow Steps, Port Alder, founded 2011. It publishes English-language poetry and translations from Portuguese, Polish and Norwegian. The catalog snapshot in `catalog/catalog.csv` is dated 17 February 2026, before the reversion request. Folders are deliberately laid out as a working drive, not by topic, and file names are inconsistent on purpose.

The one thread that runs through the whole drive: **The Drowned Orchard** (ISBN 979-8-9001-0411-9), out of print since January 2026. The Estate's written reversion request (2 March 2026, received 5 March), Clause 7 of Agreement LWE-T-2014-01 (nine months), the board motion M-2026-04-03, the reissue email thread, the cover versions, the estate consent, the distributor listing and the launch intro recording all refer to the same contract clause. Jurisdiction in the contracts ("Republic of Harrowmere") is invented.

## People
| Name | Role | Connection |
|---|---|---|
| Marguerite Oyelaran-Voss | publisher | Lantern Wharf Editions |
| Tobias Hallenbeck | editor (managing) | Lantern Wharf Editions |
| Ines Quillfeather | editor (poetry) | Lantern Wharf Editions |
| Dariusz Wenlock | designer | freelance cover and book design |
| Halvard Peake | board member (chair) | Lantern Wharf Editions |
| Ottoline Marsh | board member (treasurer) | Lantern Wharf Editions |
| Cassia Merrowby | author | The Salt Ledger; Ninety Tides |
| Jonas Pellerin-Okafor | author | Weather for Ferrymen; Almanac of Small Mercies |
| Maud Ferriday | author | A Field Guide to Closing Time; Letters to the Lighthouse Keeper's Daughter |
| Wren Tallowfield | translator (Portuguese) | The Drowned Orchard |
| Saskia Dunmore | translator (Polish) | Lanterns for the Second Winter; The Copper Choir |
| Ilse Brandvold | translator (Norwegian) | The Harbour Does Not Answer; Winter Pilots |
| Lucia Vasconcelo-Reis | estate (executor, Estate of Teodoro Vasconcelo-Reis) | rights holder, The Drowned Orchard |
| Zofia Kaminrowska | original author, Polish | rights holder, Lanterns for the Second Winter |
| Beatrix Calloway-Ng | anthologist | The Salt Almanac: Poems of Tidal Places (Fenwick & Dray Books) |
| Gunnhild Aasebo | agent, Nordlys Literary Agency | rights, The Harbour Does Not Answer |
| Ruth Ashdown-Pike | programme officer, Harrow Coast Arts Council | grant HCAC-T-2026-117 |
| Nell Cartwright-Boyd | metadata contact, Bramblegate Distribution | distributor |
| Ewan Ricketts | printer contact, Corvane Print | printer |
| Priya Dacosta | bookings, the Tallow Room | venue |

## Layout
- `catalog/catalog.csv`: 12 titles with valid ISBN-13 check digits.
- `contracts/`: 6 text-extractable PDF contracts (3 author, 3 translation) (expected fields and verbatim clause text are in `fixtures/press-eval/answer-keys/contracts_truth.json`, outside the archive).
- `correspondence/letters/`: 12 letters (9 .txt, 3 .pdf).
- `correspondence/mail-export.mbox`: 40 messages in 8 threads, 5 attachments, with Message-ID, In-Reply-To and References.
- `manuscripts/`: 4 .docx with tracked insertions and deletions (w:ins, w:del) and comments (comments.xml).
- `board/`: minutes of 14 April 2026 (.docx), 22 September 2026 (.md) and 14 February 2023 (.md).
- `recordings/`: 3 recordings (two .m4a, one .wav) (the exact spoken text is in `fixtures/press-eval/answer-keys/recordings_script.json`, outside the archive).
- `design/cover-drowned-orchard/`: three cover versions (SVG) with dates in the file names.
- `design/`: three notes on the yellow spine band (see the yellow thread below).
- `handwritten/`: README for three phone photos to be added.

## The yellow thread
Six documents, 2019 to 2026, on one colour: the yellow spine band on the poetry list. They are in four folders and have no title in common, which is the point: a search for "yellow" has to cross the press.

| Date | File | Ties to | Starts as |
|---|---|---|---|
| 12 March 2019 | `design/yellow-spine-brief_2019-03-12.md` (design brief) | the press | staff |
| 8 June 2021 | `design/yellow-proof-note_ninety-tides_2021-06-08.txt` (printer's proof note) | Ninety Tides | staff |
| 19 September 2022 | `correspondence/letters/2022-09-19_wenlock_harbour-jacket-yellow.txt` (letter, Wenlock to Quillfeather) | The Harbour Does Not Answer | private |
| 14 February 2023 | `board/minutes_2023-02-14_cover-yellow.md` (board minute, motion M-2023-02-01) | the press | staff |
| 6 May 2024 | `correspondence/letters/2024-05-06_merrowby_spine-colour.txt` (letter, Merrowby to Oyelaran-Voss) | Ninety Tides | private, stays closed |
| 24 August 2026 | `design/yellow-reissue-note_drowned-orchard_2026-08-24.md` (reissue note) | The Drowned Orchard | staff |

The four files with "yellow" in their name are opened to the AI by `make archive`. Cassia Merrowby's letter is the one a writer would keep to herself: it carries the word "yellow" but not in its name, so it is not opened, and an Explore search for "yellow" counts it as closed by its writer without showing it. No question in `fixtures/press-eval/questions.jsonl` depends on these six.

## Questions staff could ask

1. **In which territory may the Press publish Lanterns for the Second Winter?**
   `contracts/Kaminrowska_Lanterns_translation-contract_signed-2020-02-17.pdf`, Clause 2 (Grant of Rights): "the United States and its territories". Paperback only. Answer key (not part of the archive): `fixtures/press-eval/answer-keys/contracts_truth.json`.
2. **How long is the cure period before rights revert on The Drowned Orchard?**
   Nine months. `contracts/t_2014_vasconcelo-reis_orchard_RIGHTS+TRANSLATOR.pdf`, Clause 7 (Reversion), counted from the Publisher's receipt of the written request.
3. **When does that cure period end, and why?**
   5 December 2026. Request letter `correspondence/letters/2026-03-02_vasconcelo-reis_reversion-request.txt`; receipt on 5 March 2026 stated in `correspondence/letters/2026-03-09_reply_to_estate_receipt.txt`.
4. **Whose consent is needed before reprinting "Low Water at Quay Nine" in an anthology, and what is the fee?**
   The Author's (Cassia Merrowby), under `contracts/contract_merrowby_SaltLedger_2012.pdf`, Clause 7 (Permissions). Fee USD 150, split equally: `correspondence/letters/2026-05-20_tobias_to_calloway-ng_permission-granted.txt`; consent in `correspondence/letters/merrowby_consent_2026-05-27.pdf`; thread C in `correspondence/mail-export.mbox`.
5. **What did the board decide about The Drowned Orchard?**
   Motion M-2026-04-03, Item 4, to reissue in paperback and ebook, available by 30 November 2026, carried 3 to 0: `board/Minutes April 14 2026 (final).docx`. Progress in `board/minutes_2026-09-22.md`, Item 4.
6. **Which line in the reading recording mentions an auditor?**
   "A gull inspects the rope like an auditor." in `recordings/01_reading_quay-nine_and_chandlery.m4a`; exact text in `fixtures/press-eval/answer-keys/recordings_script.json` (not part of the archive).
7. **Which cover version of the reissue was approved, and when?**
   Version 3, on 19 May 2026: `design/cover-drowned-orchard/drowned-orchard_cover_v3_2026-05-19.svg`; thread B and attachment `cover-approval-v3.pdf` in `correspondence/mail-export.mbox`.
8. **When did the distributor list the reissue, and what ONIX values were corrected?**
   Listing confirmed on 2 November 2026 (inside the Clause 7 period). ONIX: Ninety Tides price 18.00 to 16.00; The Drowned Orchard ProductAvailability 51 to 20. Thread H and attachment `onix-diff.txt` in `correspondence/mail-export.mbox`; Estate's consent conditions in `correspondence/letters/estate_consent_reissue_2026-05-04.pdf`.

