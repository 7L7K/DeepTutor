const FENCE = "```";

export const CO_WRITER_SAMPLE_TEMPLATE = `# TEEECHR Co-Writer

> TEEECHR's built-in writing canvas for notes, reports, tutorials, and AI-assisted drafts.

### Features

- Support Standard Markdown / CommonMark / GFM for everyday writing
- Real-time preview for headings, tables, code, math, flowchart, and sequence diagrams
- AI editing workflows for rewrite, shorten, and expand
- HTML tag decoding for tags like <sub>, <sup>, <abbr>, and <mark>
- A practical starter draft for TEEECHR product docs and learning content

## Table of Contents

[TOCM]

[TOC]

#TEEECHR Mission
##TEEECHR Product Surface
###TEEECHR Learning Experience
####TEEECHR Co-Writer
#####TEEECHR Knowledge Layer
######TEEECHR Agent Runtime

#TEEECHR Docs [Project Overview](#deeptutor-mission "Jump to project overview")
##TEEECHR Authoring [Co-Writer Section](#deeptutor-co-writer "Jump to co-writer section")
###TEEECHR Research [Learning Note](#deeptutor-learning-note "Jump to learning note")

## Headers (Underline)

TEEECHR Learning Note
=============

TEEECHR Study Outline
-------------

### Characters

----

~~Deprecated behavior~~ <s>Legacy formatting path</s>
*Italic* _Italic_
**Emphasis** __Emphasis__
***Emphasis Italic*** ___Emphasis Italic___

Superscript: X<sub>2</sub>, Subscript: O<sup>2</sup>

**Abbreviation(link HTML abbr tag)**

The <abbr title="Large Language Model">LLM</abbr> layer powers TEEECHR while the <abbr title="Retrieval Augmented Generation">RAG</abbr> layer provides grounded knowledge support.

### Blockquotes

> TEEECHR helps students turn questions into structured understanding.
>
> "Learn deeply, write clearly.", [TEEECHR](#deeptutor-co-writer)

### Links

[TEEECHR Overview](#deeptutor-mission)

[TEEECHR Co-Writer](#deeptutor-co-writer "co-writer section")

[TEEECHR Runtime](#deeptutor-agent-runtime)

[Reference link][deeptutor-doc]

[deeptutor-doc]: #deeptutor-learning-note

### Code Blocks

#### Inline code

\`deeptutor chat --once "Summarize this section"\`

#### Code Blocks (Indented style)

    from deeptutor.runtime.orchestrator import ChatOrchestrator
    orchestrator = ChatOrchestrator()
    print("TEEECHR is ready.")

#### Python

${FENCE}python
from deeptutor.runtime.orchestrator import ChatOrchestrator
from deeptutor.core.context import UnifiedContext


async def run_demo() -> str:
    orchestrator = ChatOrchestrator()
    context = UnifiedContext(
        user_query="Explain Newton's second law",
        capability="chat",
    )
    result = await orchestrator.run(context)
    return result.get("response", "")
${FENCE}

#### JSON config

${FENCE}json
{
  "app_name": "TEEECHR",
  "default_capability": "chat",
  "enabled_tools": ["rag", "web_search", "code_execution", "reason"],
  "ui": {
    "co_writer_template": true,
    "notebook_export": true
  }
}
${FENCE}

#### HTML code

${FENCE}html
<section class="deeptutor-card">
  <h1>TEEECHR</h1>
  <p>Write, revise, and organize learning content with AI.</p>
</section>
${FENCE}

### Images

![](/logo-ver2.png)

> TEEECHR brand mark used inside the co-writer template.

### Lists

- TEEECHR Chat
- TEEECHR Co-Writer
- TEEECHR Research

1. Draft a concept note
2. Ask AI to refine it
3. Save it to a notebook

### Tables

Feature       | Description
------------- | -------------
Co-Writer     | Draft and refine Markdown content
Notebook      | Save and organize outputs
Research      | Build structured multi-step reports

| Capability    | Primary Use Case                     |
| ------------- | ------------------------------------ |
| \`chat\`       | General tutoring and guidance        |
| \`deep_solve\` | Structured problem solving           |
| \`deep_question\` | Question generation and validation |

### Markdown extras

- [x] Draft a TEEECHR product note
- [x] Add references and structure
- [ ] Polish the final explanation
  - [ ] Check headings
  - [ ] Check citations

### TeX (LaTeX)

$$ E=mc^2 $$

Inline $$E=mc^2$$ appears in physics notes, and Inline $$a^2+b^2=c^2$$ appears in geometry notes.

$$\(\sqrt{3x-1}+(1+x)^2\)$$

$$ \sin(\alpha)^{\theta}=\sum_{i=0}^{n}(x^i + \cos(f))$$

### FlowChart

${FENCE}flow
st=>start: Student asks a question
op=>operation: TEEECHR analyzes intent
cond=>condition: Need deep workflow?
chat=>operation: Answer with chat capability
solve=>operation: Route to deep solve
e=>end: Return structured response

st->op->cond
cond(no)->chat
cond(yes)->solve
chat->e
solve->e
${FENCE}

### Sequence Diagram

${FENCE}seq
Student->TEEECHR: Ask for help
TEEECHR->Notebook: Load context
Note right of TEEECHR: Collect memory\nand relevant knowledge
TEEECHR-->Student: Return guided response
Student->>TEEECHR: Request rewrite in co-writer
${FENCE}

### End
`;
