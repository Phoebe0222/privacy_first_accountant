"use client";
import { useEffect, useState } from "react";
import { api, DeductionRule, DeductionsEstimate } from "@/lib/api";

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

const USER_TYPES = [
  { value: "individual_salary", label: "Individual — Salary" },
  { value: "individual_abn", label: "Individual with ABN" },
  { value: "small_business", label: "Small Business" },
];

const CATEGORIES = [
  "food", "transport", "utilities", "software", "marketing",
  "revenue", "salary", "office", "subscription", "home_office", "other",
];

const currentYear = new Date().getFullYear();
const YEARS = Array.from({ length: 5 }, (_, i) => currentYear - i);

export default function DeductionsPage() {
  const [tab, setTab] = useState<"estimate" | "rules">("estimate");
  const [userType, setUserType] = useState("small_business");
  const [year, setYear] = useState(currentYear);
  const [estimate, setEstimate] = useState<DeductionsEstimate | null>(null);
  const [rules, setRules] = useState<DeductionRule[]>([]);
  const [loadingEstimate, setLoadingEstimate] = useState(false);
  const [loadingRules, setLoadingRules] = useState(false);
  const [editingRules, setEditingRules] = useState<Record<number, Partial<DeductionRule>>>({});
  const [showAddForm, setShowAddForm] = useState(false);
  const [newRule, setNewRule] = useState({ category: "other", rate: 1.0, label: "", note: "" });
  const [resetting, setResetting] = useState(false);
  const [savingId, setSavingId] = useState<number | null>(null);

  // Load settings on mount
  useEffect(() => {
    api.getDeductionSettings().then(({ user_type }) => setUserType(user_type)).catch(() => {});
  }, []);

  // Load estimate when year/userType changes
  useEffect(() => {
    setLoadingEstimate(true);
    api.getDeductionsEstimate(year)
      .then(setEstimate)
      .catch(() => setEstimate(null))
      .finally(() => setLoadingEstimate(false));
  }, [year, userType]);

  // Load rules when userType or tab changes
  useEffect(() => {
    if (tab !== "rules") return;
    setLoadingRules(true);
    api.getDeductionRules(userType)
      .then(setRules)
      .catch(() => setRules([]))
      .finally(() => setLoadingRules(false));
  }, [userType, tab]);

  async function handleUserTypeChange(type: string) {
    setUserType(type);
    await api.updateDeductionSettings(type).catch(() => {});
  }

  function startEdit(rule: DeductionRule) {
    setEditingRules((prev) => ({ ...prev, [rule.id]: { rate: rule.rate, label: rule.label, note: rule.note } }));
  }

  function cancelEdit(id: number) {
    setEditingRules((prev) => { const n = { ...prev }; delete n[id]; return n; });
  }

  async function saveRule(id: number) {
    const patch = editingRules[id];
    if (!patch) return;
    setSavingId(id);
    try {
      const updated = await api.updateDeductionRule(id, patch);
      setRules((prev) => prev.map((r) => (r.id === id ? updated : r)));
      cancelEdit(id);
    } finally {
      setSavingId(null);
    }
  }

  async function handleDeleteRule(id: number) {
    if (!confirm("Delete this rule?")) return;
    await api.deleteDeductionRule(id);
    setRules((prev) => prev.filter((r) => r.id !== id));
  }

  async function handleAddRule(e: React.FormEvent) {
    e.preventDefault();
    const created = await api.createDeductionRule({
      user_type: userType,
      category: newRule.category,
      rate: newRule.rate,
      label: newRule.label,
      note: newRule.note || undefined,
    } as Omit<DeductionRule, "id">);
    setRules((prev) => [...prev, created]);
    setNewRule({ category: "other", rate: 1.0, label: "", note: "" });
    setShowAddForm(false);
  }

  async function handleReset() {
    if (!confirm(`Reset all rules for "${USER_TYPES.find(u => u.value === userType)?.label}" to defaults?`)) return;
    setResetting(true);
    try {
      const resetRules = await api.resetDeductionRules(userType);
      setRules(resetRules);
    } finally {
      setResetting(false);
    }
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <h2 className="text-2xl font-bold text-gray-800">Tax Deductions</h2>

      {/* User type selector */}
      <div className="flex gap-2">
        {USER_TYPES.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => handleUserTypeChange(value)}
            className={`px-4 py-2 rounded-lg text-sm border transition-colors ${
              userType === value
                ? "bg-blue-600 text-white border-blue-600"
                : "border-gray-200 text-gray-600 hover:bg-gray-50"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {(["estimate", "rules"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
              tab === t ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t === "estimate" ? "Estimate" : "Rules"}
          </button>
        ))}
      </div>

      {tab === "estimate" && (
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <label className="text-sm text-gray-500">Year</label>
            <select
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white"
            >
              {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>

          {loadingEstimate ? (
            <p className="text-gray-400">Calculating…</p>
          ) : estimate ? (
            <>
              <div className="bg-blue-50 border border-blue-100 rounded-xl p-5 flex justify-between items-center">
                <div>
                  <p className="text-sm text-blue-700 font-medium">Estimated Total Deductible ({year})</p>
                  <p className="text-xs text-blue-500 mt-0.5">From bank CSV and manual transactions marked Business</p>
                </div>
                <p className="text-3xl font-bold text-blue-700">{fmt(estimate.total_deductible)}</p>
              </div>

              {estimate.items.length === 0 ? (
                <p className="text-gray-400 text-sm">No business expenses found for {year}. Import some bank CSV transactions to get started.</p>
              ) : (
                <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                      <tr>
                        <th className="px-4 py-3 text-left">Category</th>
                        <th className="px-4 py-3 text-right">Total Spent</th>
                        <th className="px-4 py-3 text-right">Rate</th>
                        <th className="px-4 py-3 text-right">Est. Deduction</th>
                        <th className="px-4 py-3 text-left text-gray-400">Note</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {estimate.items.map((item) => (
                        <tr key={item.category} className="hover:bg-gray-50">
                          <td className="px-4 py-3">
                            <p className="font-medium text-gray-800">{item.label}</p>
                            <p className="text-xs text-gray-400 capitalize">{item.category}</p>
                          </td>
                          <td className="px-4 py-3 text-right text-gray-600">{fmt(item.total_spent)}</td>
                          <td className="px-4 py-3 text-right text-gray-500">{(item.rate * 100).toFixed(0)}%</td>
                          <td className="px-4 py-3 text-right font-semibold text-green-700">{fmt(item.deductible_amount)}</td>
                          <td className="px-4 py-3 text-xs text-gray-400 max-w-xs">{item.note ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <p className="text-xs text-gray-400">
                Estimates only — consult a registered tax agent for final figures. Rates are based on the rules configured in the Rules tab.
              </p>
            </>
          ) : null}
        </div>
      )}

      {tab === "rules" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-500">
              Deductibility rates for <strong>{USER_TYPES.find(u => u.value === userType)?.label}</strong>
            </p>
            <div className="flex gap-2">
              <button
                onClick={handleReset}
                disabled={resetting}
                className="text-xs text-gray-400 hover:text-gray-600 border border-gray-200 px-3 py-1.5 rounded-lg disabled:opacity-50"
              >
                {resetting ? "Resetting…" : "Reset to defaults"}
              </button>
              <button
                onClick={() => setShowAddForm(!showAddForm)}
                className="text-sm bg-blue-600 text-white px-4 py-1.5 rounded-lg hover:bg-blue-700"
              >
                + Add Rule
              </button>
            </div>
          </div>

          {showAddForm && (
            <form onSubmit={handleAddRule} className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Category</label>
                <select value={newRule.category} onChange={(e) => setNewRule({ ...newRule, category: e.target.value })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm">
                  {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Rate (%)</label>
                <input type="number" min="0" max="100" step="1" required
                  value={Math.round(newRule.rate * 100)}
                  onChange={(e) => setNewRule({ ...newRule, rate: Number(e.target.value) / 100 })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Label</label>
                <input required value={newRule.label} onChange={(e) => setNewRule({ ...newRule, label: e.target.value })}
                  placeholder="e.g. Home Office" className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Note (optional)</label>
                <input value={newRule.note} onChange={(e) => setNewRule({ ...newRule, note: e.target.value })}
                  placeholder="e.g. ATO fixed rate" className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm" />
              </div>
              <div className="col-span-2 flex gap-2">
                <button type="submit" className="bg-blue-600 text-white px-4 py-1.5 rounded-lg text-sm hover:bg-blue-700">Save</button>
                <button type="button" onClick={() => setShowAddForm(false)} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
              </div>
            </form>
          )}

          {loadingRules ? (
            <p className="text-gray-400">Loading…</p>
          ) : (
            <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-gray-500 text-xs uppercase tracking-wide">
                  <tr>
                    <th className="px-4 py-3 text-left">Category</th>
                    <th className="px-4 py-3 text-left">Label</th>
                    <th className="px-4 py-3 text-right">Rate</th>
                    <th className="px-4 py-3 text-left">Note</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {rules.map((rule) => {
                    const editing = editingRules[rule.id];
                    return (
                      <tr key={rule.id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-gray-500 capitalize">{rule.category}</td>
                        <td className="px-4 py-3">
                          {editing ? (
                            <input value={editing.label ?? rule.label}
                              onChange={(e) => setEditingRules((p) => ({ ...p, [rule.id]: { ...p[rule.id], label: e.target.value } }))}
                              className="border border-gray-200 rounded px-2 py-1 text-sm w-36" />
                          ) : (
                            <span className="font-medium text-gray-800">{rule.label}</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {editing ? (
                            <input type="number" min="0" max="100" step="1"
                              value={Math.round((editing.rate ?? rule.rate) * 100)}
                              onChange={(e) => setEditingRules((p) => ({ ...p, [rule.id]: { ...p[rule.id], rate: Number(e.target.value) / 100 } }))}
                              className="border border-gray-200 rounded px-2 py-1 text-sm w-16 text-right" />
                          ) : (
                            <span className="font-medium text-gray-700">{(rule.rate * 100).toFixed(0)}%</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-400">
                          {editing ? (
                            <input value={editing.note ?? rule.note ?? ""}
                              onChange={(e) => setEditingRules((p) => ({ ...p, [rule.id]: { ...p[rule.id], note: e.target.value } }))}
                              className="border border-gray-200 rounded px-2 py-1 text-sm w-48" />
                          ) : (
                            rule.note ?? "—"
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          {editing ? (
                            <div className="flex gap-2 justify-end">
                              <button onClick={() => saveRule(rule.id)} disabled={savingId === rule.id}
                                className="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 disabled:opacity-50">
                                {savingId === rule.id ? "Saving…" : "Save"}
                              </button>
                              <button onClick={() => cancelEdit(rule.id)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
                            </div>
                          ) : (
                            <div className="flex gap-2 justify-end">
                              <button onClick={() => startEdit(rule)} className="text-xs text-gray-400 hover:text-gray-700">Edit</button>
                              <button onClick={() => handleDeleteRule(rule.id)} className="text-xs text-gray-300 hover:text-red-500">Delete</button>
                            </div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
