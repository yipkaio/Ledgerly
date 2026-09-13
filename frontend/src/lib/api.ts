export const categories = [
  "Meals and Entertainment",
  "Office Supplies",
  "Travel and Transport",
  "Utilities",
  "Software and Subscriptions",
  "Professional Fees",
  "Rent",
  "Repairs and Maintenance",
  "Inventory or Cost of Sales",
  "Other Expenses",
] as const;
export type LineItem = {
  description: string | null;
  quantity: number | null;
  unit_price: number | null;
  discount_percent: number | null;
  discount_amount: number | null;
  line_total: number | null;
};
export type Extraction = {
  vendor: string | null;
  legal_entity: string | null;
  company_registration_number: string | null;
  branch: string | null;
  receipt_number: string | null;
  date: string | null;
  currency: string | null;
  line_items: LineItem[];
  subtotal: number | null;
  tax_amount: number | null;
  total_before_rounding: number | null;
  rounding_adjustment: number | null;
  total_amount: number | null;
  cash_tendered: number | null;
  change_amount: number | null;
  payment_method: string | null;
  needs_review: boolean;
  review_reasons: string[];
};
export type Classification = {
  category: string;
  confidence: number;
  reason: string;
  source: string;
  needs_review: boolean;
  review_reasons: string[];
  workflow_decision: string;
};
export type Review = {
  decision: "APPROVED" | "REJECTED";
  reviewer: string;
  reviewed_at: string;
  note: string;
  category: string | null;
  final_data: Extraction | null;
  identity_source: string;
  override_reason: string | null;
  validation_issues: string[];
  request_id: string;
};
export type Receipt = {
  receipt_id: string;
  processing_status: string;
  created_at: string;
  business_purpose: string | null;
  ocr_text: string | null;
  ocr_engine: string | null;
  error: string | null;
  extracted_data: Extraction | null;
  classification: Classification | null;
  review: Review | null;
  review_version: number;
};
export type Row = {
  receipt_id: string;
  created_at: string;
  vendor?: string | null;
  total_amount?: number | null;
  currency?: string | null;
  processing_status?: string;
  decision?: string | null;
  review_decision?: string | null;
};
export type Page = {
  items: Row[];
  total: number;
  offset: number;
  limit: number;
};
export type ReviewRequest = {
  request_id: string;
  expected_version: number;
  decision: "APPROVED" | "REJECTED";
  reviewer: string;
  note: string;
  evidence_confirmed: true;
  category?: string;
  corrected_data?: Extraction;
  override_reason?: string;
};
export class ApiError extends Error {
  status: number;
  receiptId: string | null;
  constructor(
    message: string,
    status: number,
    receiptId: string | null = null,
  ) {
    super(message);
    this.status = status;
    this.receiptId = receiptId;
  }
}
export async function request<T>(
  path: string,
  token: string,
  options: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("X-API-Key", token);
  const { timeoutMs = 30000, ...init } = options;
  const timeout = AbortSignal.timeout(timeoutMs);
  const response = await fetch(path, {
    ...init,
    signal: init.signal ? AbortSignal.any([init.signal, timeout]) : timeout,
    headers,
    cache: "no-store",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string | { loc: (string | number)[]; msg: string }[];
    };
    const detail = Array.isArray(body.detail)
      ? body.detail
          .map((e) => `${e.loc.slice(1).join(".")}: ${e.msg}`)
          .join("; ")
      : body.detail;
    throw new ApiError(
      detail || `Request failed (${response.status})`,
      response.status,
      response.headers.get("X-Receipt-ID"),
    );
  }
  return response.json() as Promise<T>;
}
export function message(error: unknown): string {
  if (error instanceof DOMException && error.name === "TimeoutError")
    return "The server did not reply in time. Check the saved record before retrying.";
  if (error instanceof TypeError)
    return "Connection lost. Check the saved record before retrying.";
  if (error instanceof ApiError && error.status === 401)
    return "Your app API key was not accepted. Disconnect and enter the key used by this server.";
  return error instanceof Error
    ? error.message
    : "Request failed. Please try again.";
}
export function rowStatus(row: Row) {
  return (
    row.review_decision ||
    row.decision ||
    row.processing_status ||
    "REVIEW_QUEUE"
  );
}
export function amount(
  value: number | null | undefined,
  currency: string | null | undefined,
) {
  return value == null ? "—" : `${currency || ""} ${value.toFixed(2)}`.trim();
}
