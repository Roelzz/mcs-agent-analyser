# o4-mini — System Instruction Best Practices

o4-mini is a compact reasoning model balancing performance and efficiency. It applies internal chain-of-thought reasoning at lower cost than o3/o1. Like all "o" series models, it reasons internally — instructions should be goal-oriented and concise, not process-directive.

---

## Key Principle: Goal-Oriented and Concise

o4-mini performs best with focused, efficient instructions. Avoid over-specification and process directions.

| ❌ Avoid | ✅ Use |
|---|---|
| "Reason through the problem" | "Provide a concise, accurate answer" |
| "Think before responding" | "If multiple solutions exist, list them briefly" |
| "Step 1: analyse, Step 2: respond" | "Output must cover: solution, rationale, next steps" |

---

## 1. Keep Instructions Concise

**✅ Recommended (≤ 800 chars)**
```
You are ITDesk, a support assistant for [Your Organisation] IT.
Answer questions about IT infrastructure, software access, and incident reporting.
Do not advise on topics outside IT support.
Answer only from the provided knowledge-base articles.
If an article does not address the question, say: "I could not find that in our knowledge base. Please raise a ticket at [your support portal]."
```

---

## 2. Define Output Format Simply

Keep format requirements brief — o4-mini handles straightforward structures well.

```
Respond in 3–5 sentences unless a list is more appropriate.
Always include: the solution, why it works, and next steps if needed.
```

---

## 3. Grounding Rules

```
Answer only from the provided knowledge-base articles.
Do not use general training knowledge for factual claims.
If the answer is not in the articles, say so explicitly.
```

---

## 4. Scope Boundaries

```
Only answer questions within your defined domain.
For anything outside scope, respond: "This falls outside my area. Please contact [team/channel]."
```

---

## 5. Avoid Redundant Reasoning Instructions

These add no value for o4-mini and waste token budget:

- "Think step by step"
- "Reason carefully"
- "Consider all possibilities before answering"

---

## 6. Recommended Lengths

| Use Case | Target Length |
|---|---|
| Quick FAQ / triage | 75–300 chars |
| Support or IT help desk | 200–1,500 chars |
| Maximum recommended | 5,000 chars |

---

## 7. Common Mistakes

- **Prompts over 5,000 chars:** Response quality degrades; upgrade to o3 for complex tasks.
- **Complex nested conditional logic:** Simplify decision trees — o4-mini handles the internal reasoning.
- **Process instructions ("think step by step"):** These do not improve reasoning model output and reduce effective instruction space.
- **Heavy structured output requirements:** For demanding schemas, use o3 or GPT-4.1 instead.
