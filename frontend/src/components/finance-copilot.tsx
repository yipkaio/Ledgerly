import { useState } from "react";
import { Bot, LoaderCircle, MessageCircleQuestion, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Notice } from "@/components/feedback";
import { message, request } from "@/lib/api";

type Audit = {
  request_id: string;
  task: string;
  model: string;
  prompt_version: string;
  input_sha256: string;
  cached: boolean;
  created_at: string;
};
type Explanation = {
  executive_summary: string;
  exceptions: {
    exception_type: string;
    priority: "low" | "medium" | "high";
    explanation: string;
    next_action: string;
    evidence_ids: string[];
  }[];
  limitations: string[];
  advisory_only: true;
};
type Brief = {
  close_status: "ready" | "attention_required" | "insufficient_evidence";
  highlights: string[];
  attention_items: string[];
  checklist: string[];
  caveat: string;
  advisory_only: true;
};
type Answer = {
  answer: string;
  evidence: string[];
  limitations: string[];
  advisory_only: true;
};
type Result =
  | { kind: "explanation"; data: Explanation; audit: Audit }
  | { kind: "brief"; data: Brief; audit: Audit }
  | { kind: "answer"; data: Answer; audit: Audit };

export function FinanceCopilot({
  token,
  month,
  currency,
}: {
  token: string;
  month: string;
  currency: string;
}) {
  const [busy, setBusy] = useState<"explain" | "brief" | "ask" | null>(null);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  async function run(kind: "explain" | "brief" | "ask") {
    if (kind === "ask" && question.trim().length < 5) return;
    setBusy(kind);
    setError("");
    try {
      const body = { month, currency, ...(kind === "ask" ? { question: question.trim() } : {}) };
      const endpoint =
        kind === "explain"
          ? "/ai/reconciliation/explain"
          : kind === "brief"
            ? "/ai/monthly-close/brief"
            : "/ai/copilot/ask";
      const response = await request<Record<string, unknown>>(endpoint, token, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        timeoutMs: 120000,
      });
      if (kind === "explain")
        setResult({
          kind: "explanation",
          data: response.explanation as Explanation,
          audit: response.audit as Audit,
        });
      else if (kind === "brief")
        setResult({
          kind,
          data: response.brief as Brief,
          audit: response.audit as Audit,
        });
      else
        setResult({
          kind: "answer",
          data: response.answer as Answer,
          audit: response.audit as Audit,
        });
    } catch (caught) {
      setError(message(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="panel p-5 sm:p-6" aria-labelledby="finance-copilot-title">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <div className="flex items-center gap-2">
            <Bot className="text-primary" />
            <h2 id="finance-copilot-title" className="text-lg font-semibold">
              Finance Copilot
            </h2>
          </div>
          <p className="muted mt-1">
            Explain the deterministic reconciliation for {month} · {currency}.
            Copilot is read only and cannot approve, post, pay, or change a match.
          </p>
        </div>
        <span className="rounded-full border bg-muted/40 px-3 py-1 text-xs font-medium">
          Advisory only
        </span>
      </div>

      <div className="mt-5 flex flex-wrap gap-2">
        <Button variant="outline" disabled={busy !== null} onClick={() => void run("explain")}>
          {busy === "explain" ? <LoaderCircle className="animate-spin" /> : <Sparkles />}
          Explain exceptions
        </Button>
        <Button variant="outline" disabled={busy !== null} onClick={() => void run("brief")}>
          {busy === "brief" ? <LoaderCircle className="animate-spin" /> : <Sparkles />}
          Generate close brief
        </Button>
      </div>

      <form
        className="mt-4 flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          void run("ask");
        }}
      >
        <label className="sr-only" htmlFor="copilot-question">
          Ask Finance Copilot
        </label>
        <Input
          id="copilot-question"
          minLength={5}
          maxLength={500}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Which unmatched debits need receipt evidence?"
        />
        <Button disabled={busy !== null || question.trim().length < 5}>
          {busy === "ask" ? <LoaderCircle className="animate-spin" /> : <MessageCircleQuestion />}
          Ask
        </Button>
      </form>

      {error && <Notice variant="destructive">{error}</Notice>}
      {result && <CopilotResult result={result} />}
    </section>
  );
}

function CopilotResult({ result }: { result: Result }) {
  return (
    <div className="mt-5 rounded-xl border bg-muted/20 p-4" aria-live="polite">
      {result.kind === "explanation" ? (
        <>
          <h3 className="font-semibold">Exception explanation</h3>
          <p className="mt-2 text-sm">{result.data.executive_summary}</p>
          {!!result.data.exceptions.length && (
            <div className="mt-4 space-y-3">
              {result.data.exceptions.map((item, index) => (
                <article key={`${item.exception_type}-${index}`} className="rounded-lg border bg-white p-3">
                  <p className="font-medium">
                    {item.exception_type} · {item.priority} priority
                  </p>
                  <p className="mt-1 text-sm">{item.explanation}</p>
                  <p className="muted mt-2">Next: {item.next_action}</p>
                </article>
              ))}
            </div>
          )}
          <List title="Limitations" items={result.data.limitations} />
        </>
      ) : result.kind === "brief" ? (
        <>
          <h3 className="font-semibold">
            Monthly-close brief · {result.data.close_status.replaceAll("_", " ")}
          </h3>
          <List title="Highlights" items={result.data.highlights} />
          <List title="Needs attention" items={result.data.attention_items} />
          <List title="Human checklist" items={result.data.checklist} ordered />
          <p className="muted mt-4">{result.data.caveat}</p>
        </>
      ) : (
        <>
          <h3 className="font-semibold">Copilot answer</h3>
          <p className="mt-2 text-sm whitespace-pre-wrap">{result.data.answer}</p>
          <List title="Evidence used" items={result.data.evidence} />
          <List title="Limitations" items={result.data.limitations} />
        </>
      )}
      <p className="muted mt-4 border-t pt-3 text-xs">
        {result.audit.cached ? "Cached result" : "New model call"} · prompt{" "}
        {result.audit.prompt_version} · request {result.audit.request_id.slice(0, 8)}
      </p>
    </div>
  );
}

function List({
  title,
  items,
  ordered = false,
}: {
  title: string;
  items: string[];
  ordered?: boolean;
}) {
  if (!items.length) return null;
  const Tag = ordered ? "ol" : "ul";
  return (
    <div className="mt-4">
      <h4 className="text-sm font-medium">{title}</h4>
      <Tag className={`mt-2 space-y-1 pl-5 text-sm ${ordered ? "list-decimal" : "list-disc"}`}>
        {items.map((item, index) => (
          <li key={`${index}-${item}`}>{item}</li>
        ))}
      </Tag>
    </div>
  );
}
