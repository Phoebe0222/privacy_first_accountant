"use client";
import { useEffect, useState } from "react";
import { api, DeductionRule, DeductionItem, DeductionsEstimate } from "@/lib/api";

type ATORule = { id: number; title: string; description: string };

function fyStartYear() {
  const now = new Date();
  return now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
}

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

const USER_TYPES = [
  { value: "individual_salary", label: "Salary" },
  { value: "individual_abn",    label: "ABN" },
  { value: "small_business",    label: "Small Business" },
];

export default function DeductionsPage() {
  const [tab, setTab] = useState<"estimate" | "rules" | "ato">("estimate");
  const [year, setYear] = useState(fyStartYear());
  const [userType, setUserType] = useState("small_business");
  const [estimate, setEstimate] = useState<DeductionsEstimate | null>(null);
  const [rules, setRules] = useState<DeductionRule[]>([]);
  const [loading, setLoading] = useState(false);

  const fyOptions = Array.from({ length: 5 }, (_, i) => fyStartYear() - i);

  useEffect(() => {
    api.getDeductionSettings().then((s) => setUserType(s.user_type));
  }, []);

  useEffect(() => {
    if (tab === "estimate") {
      setLoading(true);
      api.getDeductionsEstimate(year).then(setEstimate).finally(() => setLoading(false));
    } else {
      api.getDeductionRules(userType).then(setRules);
    }
  }, [tab, year, userType]);

  async function switchUserType(ut: string) {
    setUserType(ut);
    await api.updateDeductionSettings(ut);
    if (tab === "estimate") {
      setLoading(true);
      api.getDeductionsEstimate(year).then(setEstimate).finally(() => setLoading(false));
    } else {
      api.getDeductionRules(ut).then(setRules);
    }
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h2 className="text-2xl font-bold text-gray-800">Deductions</h2>
        <p className="text-sm text-gray-400 mt-1">Estimated tax-deductible expenses based on bank transactions marked as business.</p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <select value={year} onChange={(e) => setYear(Number(e.target.value))}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          {fyOptions.map((y) => <option key={y} value={y}>FY {y}–{String(y + 1).slice(2)}</option>)}
        </select>
        <div className="flex gap-1">
          {USER_TYPES.map(({ value, label }) => (
            <button key={value} onClick={() => switchUserType(value)}
              className={`px-3 py-2 rounded-lg text-sm transition-colors ${
                userType === value ? "bg-blue-600 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}>
              {label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex gap-2">
          <button onClick={() => setTab("estimate")} className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === "estimate" ? "bg-gray-800 text-white" : "bg-white border border-gray-200 text-gray-600"}`}>Estimate</button>
          <button onClick={() => setTab("rules")} className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === "rules" ? "bg-gray-800 text-white" : "bg-white border border-gray-200 text-gray-600"}`}>Rules</button>
          <button onClick={() => setTab("ato")} className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === "ato" ? "bg-gray-800 text-white" : "bg-white border border-gray-200 text-gray-600"}`}>ATO Context</button>
        </div>
      </div>

      {tab === "estimate" && (loading ? <p className="text-gray-400">Calculating…</p> : estimate && <EstimateTab estimate={estimate} />)}
      {tab === "rules" && <RulesTab userType={userType} rules={rules} onRulesChange={setRules} />}
      {tab === "ato" && <ATOContextTab />}
    </div>
  );
}

function EstimateTab({ estimate }: { estimate: DeductionsEstimate }) {
  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5 flex items-center justify-between">
        <div>
          <p className="text-xs text-gray-400">{estimate.period} · {estimate.date_range}</p>
          <p className="text-xs text-gray-400 mt-0.5">Total business expenses: {fmt(estimate.total_expenses)}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-gray-400">Estimated total deductible</p>
          <p className="text-3xl font-bold text-green-600">{fmt(estimate.total_deductible)}</p>
        </div>
      </div>

      {estimate.items.length === 0 ? (
        <p className="text-gray-400 text-sm">No expense transactions found for this period.</p>
      ) : (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
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
                    <p className="text-xs text-gray-400 capitalize">{item.category.replace("_", " ")}</p>
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700">{fmt(item.total_spent)}</td>
                  <td className="px-4 py-3 text-right">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${item.rate === 1 ? "bg-green-100 text-green-700" : item.rate >= 0.5 ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-500"}`}>
                      {Math.round(item.rate * 100)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-medium text-green-700">{fmt(item.deductible_amount)}</td>
                  <td className="px-4 py-3 text-xs text-gray-400">{item.note ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-gray-400">
        Estimates only — consult a registered tax agent before lodging.
        Only bank transactions marked as Business are included.
      </p>
    </div>
  );
}

function RulesTab({ userType, rules, onRulesChange }: { userType: string; rules: DeductionRule[]; onRulesChange: (r: DeductionRule[]) => void }) {
  const [editId, setEditId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState({ rate: 0, label: "", note: "" });
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState({ category: "", rate: 100, label: "", note: "" });

  function startEdit(r: DeductionRule) {
    setEditId(r.id);
    setEditForm({ rate: Math.round(r.rate * 100), label: r.label, note: r.note ?? "" });
  }

  async function saveEdit(id: number) {
    const updated = await api.updateDeductionRule(id, { rate: editForm.rate / 100, label: editForm.label, note: editForm.note || undefined });
    onRulesChange(rules.map((r) => r.id === id ? updated : r));
    setEditId(null);
  }

  async function deleteRule(id: number) {
    if (!confirm("Delete this rule?")) return;
    await api.deleteDeductionRule(id);
    onRulesChange(rules.filter((r) => r.id !== id));
  }

  async function addRule() {
    const r = await api.createDeductionRule({ user_type: userType, category: addForm.category, rate: addForm.rate / 100, label: addForm.label, note: addForm.note || undefined });
    onRulesChange([...rules, r]);
    setShowAdd(false);
    setAddForm({ category: "", rate: 100, label: "", note: "" });
  }

  async function reset() {
    if (!confirm(`Reset all ${userType.replace("_", " ")} rules to defaults?`)) return;
    const fresh = await api.resetDeductionRules(userType);
    onRulesChange(fresh);
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <p className="text-sm text-gray-400">Deduction rates for <strong>{USER_TYPES.find((u) => u.value === userType)?.label}</strong>. Edit rates or add custom categories.</p>
        <div className="flex gap-2">
          <button onClick={reset} className="text-xs text-gray-400 hover:text-red-500 underline">Reset to defaults</button>
          <button onClick={() => setShowAdd(true)} className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700">+ Add Rule</button>
        </div>
      </div>

      {showAdd && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 grid grid-cols-4 gap-3">
          <input placeholder="category" value={addForm.category} onChange={(e) => setAddForm({ ...addForm, category: e.target.value })}
            className="border border-gray-200 rounded px-2 py-1 text-sm" />
          <input placeholder="Label" value={addForm.label} onChange={(e) => setAddForm({ ...addForm, label: e.target.value })}
            className="border border-gray-200 rounded px-2 py-1 text-sm" />
          <div className="flex items-center gap-1">
            <input type="number" min={0} max={100} value={addForm.rate} onChange={(e) => setAddForm({ ...addForm, rate: Number(e.target.value) })}
              className="border border-gray-200 rounded px-2 py-1 text-sm w-16" />
            <span className="text-sm text-gray-500">%</span>
          </div>
          <input placeholder="Note (optional)" value={addForm.note} onChange={(e) => setAddForm({ ...addForm, note: e.target.value })}
            className="border border-gray-200 rounded px-2 py-1 text-sm" />
          <div className="col-span-4 flex gap-2 justify-end">
            <button onClick={addRule} className="text-sm bg-blue-600 text-white px-4 py-1.5 rounded-lg">Save</button>
            <button onClick={() => setShowAdd(false)} className="text-sm text-gray-400 hover:text-gray-600">Cancel</button>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th className="px-4 py-3 text-left">Category</th>
              <th className="px-4 py-3 text-left">Label</th>
              <th className="px-4 py-3 text-center">Rate</th>
              <th className="px-4 py-3 text-left">Note</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {rules.map((r) => (
              <tr key={r.id} className={editId === r.id ? "bg-blue-50" : "hover:bg-gray-50"}>
                <td className="px-4 py-3 text-gray-500 text-xs capitalize">{r.category.replace("_", " ")}</td>
                <td className="px-4 py-3">
                  {editId === r.id ? (
                    <input value={editForm.label} onChange={(e) => setEditForm({ ...editForm, label: e.target.value })}
                      className="border border-blue-300 rounded px-2 py-1 text-sm w-full" />
                  ) : <span className="font-medium text-gray-800">{r.label}</span>}
                </td>
                <td className="px-4 py-3 text-center">
                  {editId === r.id ? (
                    <div className="flex items-center justify-center gap-1">
                      <input type="number" min={0} max={100} value={editForm.rate} onChange={(e) => setEditForm({ ...editForm, rate: Number(e.target.value) })}
                        className="border border-blue-300 rounded px-2 py-1 text-sm w-16 text-center" />
                      <span className="text-xs text-gray-500">%</span>
                    </div>
                  ) : (
                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${r.rate === 1 ? "bg-green-100 text-green-700" : r.rate >= 0.5 ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-500"}`}>
                      {Math.round(r.rate * 100)}%
                    </span>
                  )}
                </td>
                <td className="px-4 py-3">
                  {editId === r.id ? (
                    <input value={editForm.note} onChange={(e) => setEditForm({ ...editForm, note: e.target.value })}
                      className="border border-blue-300 rounded px-2 py-1 text-sm w-full" />
                  ) : <span className="text-xs text-gray-400">{r.note ?? ""}</span>}
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  {editId === r.id ? (
                    <span className="flex justify-end gap-2">
                      <button onClick={() => saveEdit(r.id)} className="text-xs text-blue-600 hover:text-blue-800 font-medium">Save</button>
                      <button onClick={() => setEditId(null)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
                    </span>
                  ) : (
                    <span className="flex justify-end gap-3">
                      <button onClick={() => startEdit(r)} className="text-xs text-gray-300 hover:text-blue-500">Edit</button>
                      <button onClick={() => deleteRule(r.id)} className="text-xs text-gray-300 hover:text-red-500">Delete</button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ATOContextTab() {
  const [rules, setRules] = useState<ATORule[]>([]);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");

  function load() { api.getATORules().then(setRules).catch(() => {}); }
  useEffect(() => { load(); }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api.createATORule(title.trim(), description.trim());
      setTitle("");
      setDescription("");
      load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save rule");
    }
  }

  return (
    <div className="space-y-6">
      <p className="text-sm text-gray-500">
        Add Australian tax rules, thresholds, or guidance notes. These are injected into the chat AI so it can reference them when answering tax questions.
      </p>

      <form onSubmit={handleAdd} className="bg-white border border-gray-100 rounded-xl p-6 shadow-sm space-y-3">
        <h3 className="font-semibold text-gray-700">Add Rule</h3>
        <input required value={title} onChange={(e) => setTitle(e.target.value)}
          placeholder="Title, e.g. GST Registration Threshold"
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
        <textarea required value={description} onChange={(e) => setDescription(e.target.value)}
          placeholder="e.g. Businesses with annual turnover ≥ $75,000 must register for GST."
          rows={3} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-none" />
        {error && <p className="text-red-500 text-sm">{error}</p>}
        <button type="submit" className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm hover:bg-blue-700">Add</button>
      </form>

      {rules.length === 0 ? (
        <p className="text-sm text-gray-400">No ATO rules yet.</p>
      ) : (
        <div className="bg-white border border-gray-100 rounded-xl shadow-sm overflow-hidden">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-gray-50">
              {rules.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 font-medium text-gray-700 w-48">{r.title}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{r.description}</td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => api.deleteATORule(r.id).then(load)}
                      className="text-gray-300 hover:text-red-500 text-xs">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
