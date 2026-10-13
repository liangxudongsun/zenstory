# AI writing assistant

The AI can discuss stories, draft prose, check consistency, and read or operate on project files. State the task, its evidence, and where to stop each turn.

## Describe one clear task

Include a target file, established facts, permitted changes, and a stopping point:

```text
Read Scene 1 and Three-scene outline first.
Write Scene 2 into the current draft file, in Lin He's limited viewpoint.
The bag remains at the desk; Lin He does not know the cause of the mistake.
Stop when Shen Min says “The bag isn't mine.” Do not write the ending.
```

For planning, say “Give options only; do not change files.” For drafting, specify whether to replace or append so a scene is not written twice.

## Supply context

| Evidence | How to provide it |
| --- | --- |
| Current file | Open the target; the focused file identifies saved content to read |
| Characters, outlines, earlier chapters | Name files to read, or select key text and add it to chat |
| Project materials | Attach the material item to chat |
| Library items | Select and attach from the project's Materials tab |
| Long-term background and progress | Save a short summary in AI Memory |

Up to 5 material attachments and, separately, 5 text quotes are supported. Remove irrelevant items. Context has a length budget; attaching a book does not mean reading all of it every turn.

Save recent changes before sending. If filenames are ambiguous, ask for candidates before selecting the target.

## Skills and generation modes

Use `/` in the input to select skills, or add them from the project's Skills tab. Select up to 3 for a turn, then describe the task. You can also name a skill for the AI to use as needed.

The input offers fast and deep modes. Choose for the task; a mode does not replace clear instructions or guarantee a fixed duration or word count.

## Check replies and files

Operation cards help verify file creation, edits, and reads. Candidate prose in a reply may not be saved; open the target file to check.

You can add instructions during generation; the interface reports whether they were received. Choose Stop to end further generation. File changes already made remain.

## Continue after interruption

Inspect current files and this turn's operation records before continuing:

```text
Read the current Scene 2 and list what is complete and what is missing.
Keep existing paragraphs and fill only the gap; do not append the whole scene again.
```

Retry the original task only when nothing was written and the interface offers that option. Do not repeatedly send the same request while connection state is unclear.

## Start a new chat

New Chat switches the conversation without deleting project files or AI Memory. Before switching, save accepted decisions in files and record actual progress. Identify the target and evidence again in the new chat.

If daily messages are exhausted, wait until 00:00 Beijing time the next day or check Pro. See [Plans & Benefits](billing-benefits.md).

Related: [local revision](editor.md), [AI Memory](../advanced/ai-memory.md), and [writing workflow](../advanced/workflow-tips.md).
