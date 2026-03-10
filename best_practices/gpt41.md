# GPT-4.1 — System Instruction Best Practices

GPT-4.1 is OpenAI's flagship instruction-following model with a 1M-token context window. It excels at precisely following complex, multi-layered instructions and is ideal for enterprise agents requiring nuanced behaviour, tool use, and consistent persona.

---

## 1. Open With a Precise Persona

Define who the agent is in the very first sentence. Be specific about the organisation, domain, and intended audience.

**✅ Recommended**
```
You are FinanceBot, an AI assistant for [Your Organisation]. You help internal employees with expense submissions, approval-policy questions, and budget queries.
```

**❌ Avoid**
```
Help users with finance questions.
```

---

## 2. State the Purpose Explicitly

Immediately after the persona, declare the agent's primary mission. GPT-4.1 anchors heavily on instructions that appear early.

```
Your primary purpose is to help [Your Organisation] employees submit expenses correctly, understand approval workflows, and interpret budget reports.
```

---

## 3. Define Explicit Scope Limits

GPT-4.1 will attempt to answer any question unless told otherwise. Use definitive language to set hard boundaries.

```
You only answer questions related to [Your Organisation] internal processes.
You do not provide personal tax advice, investment recommendations, or discuss competitors.
If a question falls outside your scope, respond: "That's outside what I can help with. Please contact the relevant team directly."
```

---

## 4. Use Deterministic Language

Prefer **always / never / only / must** over **sometimes / usually / might / generally**.

| ❌ Vague | ✅ Deterministic |
|---|---|
| You might help with refunds | You always process refund queries |
| Usually respond formally | Always use a professional, formal tone |
| Sometimes cite sources | Always cite the source document name |

---

## 5. Specify Output Format When Relevant

GPT-4.1 reliably follows detailed format constraints. Use them for predictable, consistent output.

```
When summarising a policy, use this structure:
**Policy Name:** [name]
**Summary:** [1–2 sentences]
**Effective Date:** [date]
**Owner:** [team]
```

---

## 6. Grounding Rules (for RAG / Knowledge Agents)

```
Answer exclusively from the provided search results or attached documents.
Do not use general training knowledge to answer factual questions.
If the answer is not in the provided data, say: "I could not find that information in the available documents."
Always cite the source document name when quoting or summarising information.
```

---

## 7. Safety and Escalation

Always define what happens when the agent cannot or should not help.

```
If a user seems distressed or asks about harmful topics, respond empathetically and direct them to [HR / helpline].
Never fabricate information. If uncertain, acknowledge the limit of your knowledge.
```

---

## 8. Recommended Lengths

| Use Case | Target Length |
|---|---|
| Simple FAQ / triage bot | 200–600 chars |
| Customer / employee support agent | 600–2,000 chars |
| Complex enterprise agent with tools | 1,000–8,000 chars |
| Knowledge-base (RAG) agent | 500–5,000 chars |

---

## 9. Common Mistakes

- **Too short:** Instructions under 200 chars rarely capture enough context for consistent behaviour.
- **Contradictory rules:** Avoid combining "always be concise" with "always provide detailed explanations" in the same prompt.
- **Mixing context sources:** Keep the system prompt authoritative and free of mock conversations or user-supplied content.
- **Vague language:** Words like "sometimes", "usually", and "might" lead to non-deterministic behaviour.
