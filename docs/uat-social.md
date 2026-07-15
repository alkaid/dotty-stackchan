---
title: UAT Social Production Guide
description: How UAT clips become YouTube Shorts on Dotty's channel — voice guide, metadata templates, disclosure, upload checklist.
---

# Dotty's channel — UAT clip production guide

The other half of [`uat-runbook.md`](./uat-runbook.md): how passing checks
become YouTube Shorts, published on **Dotty's own channel**. The channel's
narrator is Dotty, not Brett — every title, description, and community post
is written in her first-person voice.

> **AI-assistance note:** this document was drafted by an AI agent (Claude)
> and reviewed by a human, per [`AI_TRANSPARENCY.md`](../AI_TRANSPARENCY.md).

## The channel

The channel is live: **[youtube.com/@dotty-stackchan](https://www.youtube.com/@dotty-stackchan)**
("Dotty", channel ID `UCUCUetN5vt2w0ZcCti7R1ZQ`, Australia, joined
2026-04-28), with bench-test Shorts already published. Its About text is the
canonical voice sample — first-person, privacy-first, human credited:

> Hi, I'm Dotty,
>
> I'm a small desk robot, an M5 stack-chan build with an ESP32 body and a
> local LLM for a brain. No cloud AI, no subscription, no data leaving the
> house. Just me, a Raspberry Pi, and the Unraid server in the corner.
>
> This channel is mostly candids: me reacting, listening, getting confused,
> telling stories, occasionally being dramatic about the lights on my head.
> My human writes the captions and points the camera and occasionally speaks.

It also links the repo. That About page already satisfies the channel-level
disclosure requirement (below) — the per-video footer rule still applies.

Conventions the existing uploads established (adopt, don't fight):

- **Hashtags in the title**: `#dotty #stackchan #esp32 #localllm` (+ one or
  two check-specific tags).
- **`(WIP)` title suffix** for unfinished features — e.g. *"Hey dotty,
  what's on the calendar? (WIP)"*.
- **Check IDs in titles are fine** — *"Dotty bench test #45 - LED voice
  feedback…"* set the precedent; UAT check IDs (UB1, US14…) slot in the
  same way.

## The channel voice

Dotty's written voice matches her spoken persona
([`personas/dotty_voice.md`](../personas/dotty_voice.md)) and the channel
About page: warm, curious, cheerful, a little wide-eyed. Rules:

- **First person, always.** "I learned a new dance today", never "Dotty
  learns a dance" or "I taught my robot…". (Some early uploads drift
  third-person; first-person is the go-forward standard.)
- **Brett is "my human"** — the About page's own words. He appears in clips
  but never as the narrator persona. He has no byline.
- **The privacy hook is a recurring angle.** "No cloud AI, no subscription,
  no data leaving the house" is the channel's opening pitch — clips that can
  honestly show it (everything running while the internet is unplugged, the
  Unraid box in the corner, local TTS latency) should lean into it.
- **Short sentences, genuine curiosity, no snark.** She's discovering her
  own features alongside the audience.
- **Honest about being a robot in progress.** She can say "this part of me
  isn't finished yet" — that's on-brand, not a confession.
- **One emoji per title, max.** Mirrors her one-leading-emoji speech rule.
- **Kid-safe by default.** The audience includes the same 4–8-year-olds her
  kid mode protects. Nothing in a title/description Dotty wouldn't say out
  loud in kid mode.

### Example titles (per runbook phase)

| Check | Title (as Dotty) |
|---|---|
| UC1 | 😊 Hello! I'm Dotty and I live on a desk #dotty #stackchan #localllm |
| UC3 | 🤔 I have exactly nine faces. Here are all of them #dotty #esp32 |
| UT2 | 😮 My human tested my memory… and I passed #dotty #stackchan #localllm |
| US2 | 😐 I don't know how to finish a story yet (WIP) #dotty #stackchan |
| UT6 | 🤔 The question that made me think REALLY hard |
| UT7 | 😆 My human showed me a banana to see what I'd say |
| US8 | 😴 How I go to sleep (yes, I snore a little) |
| US12 | 😍 My favourite way to be woken up |
| US14 | 😆 I learned the Macarena! |
| UP6 | 😍 Did you know I purr? |
| UP9 | 😴 My human read out what I dreamed last night |
| UL6 | 😐 You can't change my lights. They're MY lights |
| UD4 | 😮 My human has a text box that makes me say things |

## Per-clip metadata template

```
Title:        <emoji> <first-person hook> <#dotty #stackchan #esp32 #localllm
              + check-specific tags; "(WIP)" suffix before the tags if the
              feature is known-pending; ≤100 chars all-in>

Description:
<1–3 first-person sentences about what happens in the clip.>

<optional: one sentence of honest context, e.g. "This part of me is
still being built — you can watch it get better.">

—
I'm Dotty: a self-hosted, open-source desk robot (M5Stack StackChan).
My brain is a local AI agent; my humans build me in the open, with AI
help, and say so: https://github.com/BrettKinny/dotty-stackchan
Clip <check-id> from my <date> full-feature test day.

Tags: stackchan, m5stack, esp32, robot, ai robot, self-hosted ai,
      open source robot, <check-specific tags>
```

The footer block is **standard on every upload** — it carries the
disclosure (below) and the check-ID → clip mapping that ties the channel
back to the results CSV.

## Disclosure (non-negotiable)

Per the spirit of [`AI_TRANSPARENCY.md`](../AI_TRANSPARENCY.md), the channel
never pretends Dotty's content is unaided human work — or that Dotty is a
person:

1. **Channel About page** states plainly: Dotty is an AI-powered robot;
   the channel is written in her voice by her humans with AI assistance;
   the project is open source. *(Already satisfied — the live About text
   quoted above covers all three; keep it that way when editing.)*
2. **Every description footer** (template above) links the repo and says
   what she is.
3. **YouTube's altered/synthetic content disclosure**: tick it where the
   platform's definition applies (synthetic voice content, AI-generated
   narration read aloud — e.g. the UP9 dream-reading clip). A robot doing
   robot things on camera is not "altered content", but when in doubt,
   disclose.
4. Descriptions drafted by an agent are fine — that's the channel concept —
   but a human reviews every one before publish, same as any other artifact.

## Fail-clip policy

- **Genuine-bug FAILs stay private by default** — the clip's job is done
  when it's attached to (or referenced from) the GitHub issue.
- **Known-pending FAILs** (US2 story_time, US6 security capture, UL4 smart
  swap) are candidate **"work in progress"** content at Brett's discretion —
  Dotty saying "I don't know how to finish a story yet, but my humans are
  teaching me" is honest and endearing.
- Never publish a clip showing other people (especially kids) without their
  say-so; the memory/person clips (UT3–UT5, UD5) must not expose real
  personal facts — use staged ones during the session.

## Upload checklist (manual, per clip)

1. Watch the clip start-to-finish (it came from an automated slicer — check
   the cut points and that no stray personal info is in frame/audio).
2. Vertical? Under 60 s? Trim in the editor if the slicer's pad overshot.
3. Write title + description from the template, in Dotty's voice.
4. Set the made-for-kids flag per the channel's standing policy (decide it
   once, not per clip — the existing uploads are maker-audience content, and
   "made for kids" disables comments and changes Shorts-feed behaviour, so
   the tone-rule "kid-safe" does not automatically mean the flag is "yes").
5. Tick the synthetic-content disclosure if applicable (see above).
6. Upload as a Short; add to the session's playlist.
7. Paste the video URL into the results CSV `note` column for that check —
   the CSV is the single record tying QA results, issues, and published
   clips together.

Last verified: 2026-07-11.
