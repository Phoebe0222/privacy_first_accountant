"use client";
import { useEffect, useState } from "react";
import { api, ReconciliationMatch } from "@/lib/api";

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

function ConfBadge({ v }: { v: number }) {
  const pct = Math.round(v * 100);
  const cls = pct >= 90 ? "bg-green-100 text-green-700" : pct >= 80 ? "bg-yellow-100 text-yellow-700" : "bg-red-100 text-red-700";
  return <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${cls}`}>{pct}%</span>;
}

export default function ReconciliationPage() {
  const [summary, setSummary] = useState<{ total_bank: number; total_receipts: number; matched: number; unmatched_bank: number; unmatched_receipts: number } | null>(null);
  const [matches, setMatches] = useState<ReconciliationMatch[]>([]);
  const [imports, setImports] = useState<{ source: string; source_ref: string; count: number; date_from: string; date_to: string }[]>([]);
  const [running, setRunning] = useState<string | null>(null);
  const [tab, setTab] = useState<"matches" | "unmatched">("matches");

  async function load() {
    const [s, m, imp] = await Promise.all([
      api.getReconciliationSummary(),
      api.getReconciliationMatches(),
      api.getImportHistory(),
    ]);
    setSummary(s);
    setMatches(m.filter((x) => x.status !== "rejected"));
    setImports(imp.filter((i) => i.source === "bank_csv"));
  }

  useEffect(() => { load(); }, []);

  async function runReconcile(sourceRef?: string) {
    setRunning(sourceRef ?? "all");
    try {
      const r = await api.runAutoReconcile();
      alert(`Done: ${r.new_matches} new matches`);
      await load();
    } finally {
      setRunning(null);
    }
  }

  async function confirm(id: number) {
    await api.updateMatch(id, "confirmed");
    await load();
  }

  async function reject(id: number) {
    await api.updateMatch(id, "rejected");
    await load();
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-800">Reconciliation</h2>
        <button
          onClick={() => runReconcile()}
          disabled={running !== null}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {running === "all" ? "Running…" : "Run Auto-Reconcile"}
        </button>
      </div>

      {/* Summary stats */}
      {summary && (
        <div className="grid grid-cols-5 gap-3">
          {[
            { label: "Bank transactions", value: summary.total_bank },
            { label: "Receipts", value: summary.total_receipts },
            { label: "Matched", value: summary.matched, green: true },
            { label: "Unmatched bank", value: summary.unmatched_bank, warn: true },
            { label: "Unmatched receipts", value: summary.unmatched_receipts, warn: true },
          ].map(({ label, value, green, warn }) => (
            <div key={label} className="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
              <p className="text-xs text-gray-400">{label}</p>
              <p className={`text-2xl font-bold mt-1 ${green ? "text-green-600" : warn && value > 0 ? "text-amber-500" : "text-gray-800"}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Bank imports */}
      {imports.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-gray-500">Bank statement imports</h3>
          <div className="bg-white border border-gray-100 rounded-xl shadow-sm overflow-hidden">
            <table className="w-full text-sm">
              <tbody className="divide-y divide-gray-50">
                {imports.map((imp) => (
                  <tr key={imp.source_ref} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-700">{imp.source_ref}</p>
                      <p className="text-xs text-gray-400">{imp.date_from} — {imp.date_to} · {imp.count} transactions</p>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => runReconcile(imp.source_ref)}
                        disabled={running !== null}
                        className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded-lg disabled:opacity-50"
                      >
                        {running === imp.source_ref ? "Running…" : "Reconcile this file"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Matches tabs */}
      <div className="flex gap-2">
        <button onClick={() => setTab("matches")} className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === "matches" ? "bg-blue-600 text-white" : "bg-white border border-gray-200 text-gray-600"}`}>
          Matches <span className="ml-1 text-xs opacity-70">({matches.length})</span>
        </button>
        <button onClick={() => setTab("unmatched")} className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === "unmatched" ? "bg-blue-600 text-white" : "bg-white border border-gray-200 text-gray-600"}`}>
          Unmatched bank {summary && summary.unmatched_bank > 0 && <span className="ml-1 bg-amber-500 text-white text-xs rounded-full px-1.5">{summary.unmatched_bank}</span>}
        </button>
      </div>

      {tab === "matches" && (
        matches.length === 0 ? (
          <p className="text-gray-400 text-sm">No matches yet. Run auto-reconcile to find matches.</p>
        ) : (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3 text-left">Bank transaction</th>
                  <th className="px-4 py-3 text-left">Receipt</th>
                  <th className="px-4 py-3 text-center">Conf.</th>
                  <th className="px-4 py-3 text-center">Status</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {matches.map((m) => (
                  <tr key={m.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-800">{m.bank?.vendor ?? "—"}</p>
                      <p className="text-xs text-gray-400">{m.bank?.date} · {m.bank ? fmt(m.bank.amount) : ""}</p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-800">{m.receipt?.vendor ?? "—"}</p>
                      <p className="text-xs text-gray-400">{m.receipt?.date} · {m.receipt ? fmt(m.receipt.amount) : ""} · {m.receipt?.source}</p>
                    </td>
                    <td className="px-4 py-3 text-center"><ConfBadge v={m.confidence} /></td>
                    <td className="px-4 py-3 text-center">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded ${m.status === "confirmed" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}>
                        {m.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      {m.status !== "confirmed" && (
                        <button onClick={() => confirm(m.id)} className="text-xs text-gray-300 hover:text-green-600 mr-2">✓ Confirm</button>
                      )}
                      <button onClick={() => reject(m.id)} className="text-xs text-gray-300 hover:text-red-500">✕ Reject</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {tab === "unmatched" && <UnmatchedBank />}
    </div>
  );
}

function UnmatchedBank() {
  const [items, setItems] = useState<{ id: number; date: string; vendor: string; amount: number; type: string }[]>([]);
  useEffect(() => { api.getUnmatchedBank().then(setItems); }, []);
  function fmt(n: number) { return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n); }
  if (items.length === 0) return <p className="text-gray-400 text-sm">All bank transactions are matched.</p>;
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-4 py-3 text-left">Date</th>
            <th className="px-4 py-3 text-left">Vendor</th>
            <th className="px-4 py-3 text-right">Amount</th>
            <th className="px-4 py-3 text-left">Type</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {items.map((t) => (
            <tr key={t.id} className="hover:bg-gray-50">
              <td className="px-4 py-3 text-gray-600">{t.date}</td>
              <td className="px-4 py-3 font-medium text-gray-800">{t.vendor}</td>
              <td className={`px-4 py-3 text-right font-medium ${t.type === "income" ? "text-green-600" : "text-gray-800"}`}>{fmt(t.amount)}</td>
              <td className="px-4 py-3"><span className={`text-xs px-2 py-0.5 rounded ${t.type === "income" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>{t.type}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
