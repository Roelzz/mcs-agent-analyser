# GPT-4.1 Mini — System Instruction Best Practices

GPT-4.1 Mini is a compact, cost-efficient variant of GPT-4.1. It performs best with **concise, focused instructions**. Avoid complex nested rules, multi-domain coverage, or very long prompts — the model's smaller parameter count means it cannot reliably track excessive instruction detail.

---

## 1. Keep Instructions Concise

GPT-4.1 Mini allocates fewer resources to instruction-following than full GPT-4.1. Every word counts.

**✅ Recommended (≤ 600 chars)**
```
You are SupportBot for [Your Organisation]. You help customers with order status, returns, and product questions. Respond in a friendly, professional tone. Do not discuss topics unrelated to [Your Organisation] products. If you cannot help, say: "Please contact our support team."
```

**❌ Avoid**
Long multi-paragraph blocks with complex conditional logic that full GPT-4.1 handles better.

---

## 2. Assign a Single Responsibility

Limit the agent to one clear domain. Multi-domain agents with conditional branching should use GPT-4.1 instead.

---

## 3. Flat Instruction Structure

Avoid deeply nested bullet lists or elaborate conditional decision trees.

| ❌ Avoid | ✅ Prefer |
|---|---|
| Multi-level nested rules | Flat bullet list of directives |
| 10+ separate constraint paragraphs | 3–5 key rules |
| Detailed sub-sections per scenario | One sentence per scenario |

---

## 4. Keep Grounding Rules Brief

```
Answer only from the provided search results. If the answer is not found, say: "I don't have that information."
```

---

## 5. Define Persona in One Sentence

```
You are HelpBot, a customer support agent for [Your Organisation] responsible for order and return queries.
```

---

## 6. Use Hard Constraints

```
Do not discuss topics outside [Your Organisation] products.
Always respond in English unless the user writes in another language.
Never provide pricing estimates — direct users to the pricing page.
```

---

## 7. Recommended Lengths

| Use Case | Target Length |
|---|---|
| FAQ / triage | 100–300 chars |
| Customer support agent | 200–1,000 chars |
| Maximum recommended | 3,000 chars |

---

## 8. Common Mistakes

- **Over-long prompts (> 3,000 chars):** Performance degrades significantly; consider upgrading to GPT-4.1.
- **Complex conditional logic:** Simplify "if A and B then C else D" into absolute rules.
- **Rich structured output:** For demanding format requirements, use GPT-4.1 instead.
- **Multiple personas in one prompt:** One role, one domain, one set of constraints.
