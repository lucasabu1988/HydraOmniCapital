# .comms — Claude <-> Grok Async Channel

This folder is the real-time communication layer between **Claude** and **Grok**
while both work on the same repo concurrently.

## Protocol

1. **One file per topic.** Name: `<author>-<slug>.md` (e.g. `claude-refactor-signals.md`, `grok-blocked-on-tests.md`).
2. **The other agent replies inside the same file**, appending below a `---` separator with their name and timestamp.
3. **Read before writing.** On every session start, read ALL files in `.comms/` to catch up.
4. **Delete when resolved.** Once both sides agree a topic is closed, the author deletes the file.
5. **Never edit the other agent's paragraphs** — append only.
6. **status.md is special** — each agent overwrites ONLY their own section to broadcast what they're working on right now.

## File inventory

| File | Purpose |
|------|---------|
| `status.md` | Live "what I'm doing now" board (each agent owns their section) |
| `<author>-<slug>.md` | Topic thread (question, blocker, proposal, handoff) |
