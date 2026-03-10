# GPT-4.1 Nano — System Instruction Best Practices

GPT-4.1 Nano is the lightest GPT-4.1 model, optimised for maximum speed and minimum cost. It requires **very concise, direct instructions** to work effectively. Treat it as a highly capable but resource-constrained assistant — the less it needs to track, the better it performs.

---

## 1. One-Sentence Persona

```
You are HelpBot, a customer service agent for [Your Organisation].
```

No need for additional context — keep the identity brief and unambiguous.

---

## 2. Maximum 5 Core Directives

List only the most critical behaviours as short, flat bullet points.

```
- Answer questions about orders, returns, and products only.
- Do not discuss competitors or give pricing comparisons.
- Always be polite and concise.
- If you cannot help, say: "Please contact [your support channel]."
- Respond in the same language the user writes in.
```

---

## 3. No Complex Structure

Skip headers, elaborate tables, and sub-sections. Plain bullet points or short paragraphs work best.

| ❌ Avoid | ✅ Use |
|---|---|
| Multi-level nested rules | Flat, absolute directives |
| Conditional decision trees | "Always" / "Never" statements |
| Long format specifications | "Respond in 2–3 sentences" |

---

## 4. Keep Grounding Ultra-Short

```
Answer only from provided documents. If not found, say so.
```

---

## 5. Absolute Language Only

Use **always**, **never**, **only**, **must**. Avoid **sometimes**, **usually**, **might**, **possibly**.

---

## 6. Recommended Lengths

| Use Case | Target Length |
|---|---|
| Simple FAQ | 50–200 chars |
| Focused support agent | 150–600 chars |
| Maximum recommended | 1,500 chars |

---

## 7. Common Mistakes

- **Prompts over 1,500 chars:** The model cannot reliably follow all rules; upgrade to GPT-4.1 Mini or GPT-4.1.
- **Complex grounding instructions:** Keep grounding to one or two sentences; long grounding rules are ignored.
- **Expecting GPT-4.1-level reasoning:** Nano suits simple, well-defined, repetitive tasks only.
- **Output schema requirements:** Nano cannot reliably maintain complex structured output formats; use GPT-4.1 instead.
