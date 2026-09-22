import { Clock3 } from "lucide-react";
import { Status } from "@/components/feedback";
import type { PaymentEvent } from "@/lib/api";

function displayState(value: string) {
  return value === "CLEAR" ? "Manual status cleared" : value.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function PaymentHistory({ events, compact = false }: { events: PaymentEvent[]; compact?: boolean }) {
  const content = <>
    {!compact && <div className="flex items-center gap-3"><span className="rounded-lg bg-emerald-50 p-2 text-emerald-700"><Clock3 className="size-5" /></span><div><h2 className="text-lg font-semibold">Payment-status history</h2><p className="muted">Recorded follow-ups; no payment is initiated here.</p></div></div>}
    <ol className="mt-3 space-y-3">
      {events.map((event, index) => {
        const previous = event.previous_state || (events[index + 1]?.state === "CLEAR" ? "NO_BANK_MATCH" : events[index + 1]?.state) || "NO_BANK_MATCH";
        return <li key={event.version} className="rounded-lg border bg-white p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2"><span className="text-muted-foreground">{displayState(previous)} →</span>{event.state === "CLEAR" ? <span className="font-medium">Manual status cleared</span> : <Status value={event.state} />}<span className="ml-auto text-xs text-muted-foreground">{new Date(event.occurred_at).toLocaleString("en-SG")}</span></div>
          <p className="mt-2"><strong>{event.actor}</strong> · {event.note}</p>
          {event.invoice_due_date && <p className="mt-1 text-xs text-muted-foreground">Invoice due: {event.invoice_due_date}</p>}
          {event.planned_payment_date && <p className="mt-1 text-xs text-muted-foreground">Planned payment: {event.planned_payment_date}</p>}
        </li>;
      })}
    </ol>
  </>;
  return compact ? <div className="border-t bg-muted/30 px-4 py-3">{content}</div> : <section className="panel p-5 sm:p-6" aria-label="Payment-status history">{content}</section>;
}
