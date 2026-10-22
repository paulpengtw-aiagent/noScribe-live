# noScribe Live: notes for agents

The live/ web viewer never starts transcriptions: during demos the owner runs the noScribe CLI with their usual flags, and the viewer only watches that run (via an opt-in feed from the CLI) and streams its segments to the browser at localhost. Keep the CLI's normal behaviour unchanged when the feed is off, and don't copy AICSS Pro components; build the aicss.dev look from free components or original code.

The 「緋紅」/"Crimson" theme uses a client's corporate colours (red Pantone 7622 C ≈ #93272C, navy 2955 C ≈ #003865, cool grays, cream, sparing gold). Never name that client anywhere (UI, docs, commits, PR text), and never use their logo, mascot or brick auxiliary pattern: colours only.

UI component licences: the owner approved animate-ui (MIT + Commons Clause) for this project, because it is consulting work and the product is not sold (2026-10-22). The free tiers of aicss.dev, affectui.com, obsidianui.dev and uiarc.dev are MIT and may be used. Record each component's licence in live/README.md's licensing section before copying it.
