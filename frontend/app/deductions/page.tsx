"use client";
import { useEffect, useState } from "react";
import { api, DeductionRule, DeductionSection, DeductionsEstimate, AITaxEstimate, AITaxItem, AITaxSection } from "@/lib/api";

type ATORule = { id: number; title: string; description: string };

function fyStartYear() {
  const now = new Date();
  return now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
}

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

export default function DeductionsPage() {
  const [tab, setTab] = useState<"estimate" | "ai" | "rules" | "ato">("estimate");
  const [year, setYear] = useState(fyStartYear());
  const [userType, setUserType] = useState("small_business");
  const [estimate, setEstimate] = useState<DeductionsEstimate | null>(null);
  const [aiEstimate, setAiEstimate] = useState<AITaxEstimate | null>(null);
  const [incomeType, setIncomeType] = useState("both");
  const [loading, setLoading] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);

  const fyOptions = Array.from({ length: 5 }, (_, i) => fyStartYear() - i);

  useEffect(() => {
    api.getDeductionSettings().then((s) => setUserType(s.user_type));
    api.getTaxProfile().then((p) => setIncomeType(p.income_type));
  }, []);

  useEffect(() => {
    if (tab === "estimate") {
      setLoading(true);
      api.getDeductionsEstimate(year).then(setEstimate).finally(() => setLoading(false));
    }
  }, [tab, year, userType]);

  useEffect(() => {
    setAiEstimate(null);
    setAiLoading(false);
  }, [year]);

  function runAiEstimate(forceRefresh: boolean) {
    setAiLoading(true);
    if (forceRefresh) setAiEstimate(null);
    api.getAITaxEstimate(year, forceRefresh)
      .then(setAiEstimate)
      .finally(() => setAiLoading(false));
  }

  async function handleCarryforwardChange(value: number) {
    await api.updateDeductionSettings({ user_type: userType, business_loss_carryforward: value });
    setLoading(true);
    api.getDeductionsEstimate(year).then(setEstimate).finally(() => setLoading(false));
  }

  return (
    <div className="space-y-6 max-w-4xl">
      <div>
        <h2 className="text-2xl font-bold text-gray-800">Deductions</h2>
        <p className="text-sm text-gray-400 mt-1">Estimated tax-deductible expenses based on bank transactions marked as Business or Employment.</p>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-3">
        <select value={year} onChange={(e) => setYear(Number(e.target.value))}
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white">
          {fyOptions.map((y) => <option key={y} value={y}>FY {y}–{String(y + 1).slice(2)}</option>)}
        </select>
        <div className="ml-auto flex gap-2">
          <button onClick={() => setTab("estimate")} className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === "estimate" ? "bg-gray-800 text-white" : "bg-white border border-gray-200 text-gray-600"}`}>Estimate</button>
          <button onClick={() => setTab("ai")} className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === "ai" ? "bg-gray-800 text-white" : "bg-white border border-gray-200 text-gray-600"}`}>AI Estimate</button>
          <button onClick={() => setTab("rules")} className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === "rules" ? "bg-gray-800 text-white" : "bg-white border border-gray-200 text-gray-600"}`}>Rules</button>
          <button onClick={() => setTab("ato")} className={`px-4 py-2 rounded-lg text-sm font-medium ${tab === "ato" ? "bg-gray-800 text-white" : "bg-white border border-gray-200 text-gray-600"}`}>ATO Context</button>
        </div>
      </div>

      {tab === "estimate" && (loading ? <p className="text-gray-400">Calculating…</p> : estimate && <EstimateTab estimate={estimate} incomeType={incomeType} onCarryforwardChange={handleCarryforwardChange} />)}
      {tab === "ai" && (
        aiLoading ? (
          <div className="flex flex-col items-center gap-4 py-16">
            <svg className="animate-spin h-8 w-8 text-blue-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            <div className="text-center space-y-1">
              <p className="text-gray-600 font-medium">Analysing transactions with ATO rules…</p>
              <p className="text-xs text-gray-400">This may take a minute — the AI is assessing each expense category.</p>
            </div>
          </div>
        ) : aiEstimate ? (
          <div className="space-y-4">
            <div className="flex justify-end">
              <button onClick={() => runAiEstimate(true)} className="text-xs text-gray-400 hover:text-gray-600 underline">
                Re-run AI
              </button>
            </div>
            <AIEstimateTab result={aiEstimate} incomeType={incomeType} />
          </div>
        ) : (
          <div className="flex flex-col items-center gap-4 py-16 text-center">
            <p className="text-sm text-gray-500 max-w-sm">
              The AI tax agent uses ATO guidance to assess deductibility of each expense category and estimate tax payable.
            </p>
            <button
              onClick={() => runAiEstimate(false)}
              className="bg-blue-600 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
            >
              Run AI Estimate
            </button>
          </div>
        )
      )}
      {tab === "rules" && <RulesTab userType={userType} incomeType={incomeType} />}
      {tab === "ato" && <ATOContextTab />}
    </div>
  );
}

function SectionTable({ section, emptyMsg }: { section: DeductionSection; emptyMsg: string }) {
  if (section.items.length === 0) return <p className="text-sm text-gray-400">{emptyMsg}</p>;
  return (
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
          {section.items.map((item) => (
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
  );
}

function EstimateSectionHeader({ label, section }: { label: string; section: DeductionSection }) {
  return (
    <div className="grid grid-cols-3 gap-3 text-center text-sm">
      <div>
        <p className="text-xs text-gray-400">{label} Income</p>
        <p className="font-bold text-green-600">{fmt(section.income)}</p>
      </div>
      <div>
        <p className="text-xs text-gray-400">Deductible</p>
        <p className="font-bold text-blue-600">− {fmt(section.total_deductible)}</p>
      </div>
      <div>
        <p className="text-xs text-gray-400">Taxable</p>
        <p className="font-bold text-gray-800">{fmt(section.taxable_income)}</p>
      </div>
    </div>
  );
}

function TaxPosition({ combined, source }: { combined: DeductionsEstimate["combined"]; source: string }) {
  const hasPAYG = combined.payg_withheld > 0;
  return (
    <div className="bg-gray-50 rounded-xl border border-gray-100 p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-gray-700">Tax Position</h3>
        {source === "settings" && (
          <span className="text-xs bg-blue-50 text-blue-600 border border-blue-100 rounded px-2 py-0.5">
            Salary from Tax Settings
          </span>
        )}
      </div>
      <div className="space-y-1.5 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-500">Taxable income</span>
          <span className="font-medium">{fmt(combined.taxable_income ?? combined.salary_taxable)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Income tax liability</span>
          <span className="font-medium text-red-500">− {fmt(combined.income_tax)}</span>
        </div>
        {hasPAYG ? (
          <>
            <div className="flex justify-between">
              <span className="text-gray-500">PAYG withheld</span>
              <span className="font-medium text-green-600">+ {fmt(combined.payg_withheld)}</span>
            </div>
            <div className="flex justify-between border-t border-gray-200 pt-1.5 mt-1">
              {combined.tax_owing > 0 ? (
                <>
                  <span className="font-semibold text-gray-700">Est. tax to pay</span>
                  <span className="font-bold text-red-500">{fmt(combined.tax_owing)}</span>
                </>
              ) : (
                <>
                  <span className="font-semibold text-gray-700">Est. tax refund</span>
                  <span className="font-bold text-green-600">{fmt(combined.tax_refund)}</span>
                </>
              )}
            </div>
          </>
        ) : (
          <p className="text-xs text-gray-400 pt-1">
            Enter PAYG withheld in{" "}
            <a href="/tax-settings" className="text-blue-500 hover:underline">Tax Settings</a>{" "}
            to see tax to pay / refund.
          </p>
        )}
      </div>
    </div>
  );
}

function CarryforwardEditor({ balance, onSave }: { balance: number; onSave: (value: number) => Promise<void> }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(balance));
  const [saving, setSaving] = useState(false);

  useEffect(() => { setValue(String(balance)); }, [balance]);

  async function save() {
    setSaving(true);
    try {
      await onSave(parseFloat(value) || 0);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex items-center justify-between text-sm gap-2">
      <span className="text-gray-500">Loss carryforward from prior years</span>
      {editing ? (
        <span className="flex items-center gap-2">
          <div className="relative">
            <span className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400 text-xs">$</span>
            <input type="number" min={0} step={0.01} value={value} onChange={(e) => setValue(e.target.value)}
              className="border border-gray-200 rounded px-2 py-1 pl-5 text-sm w-28" />
          </div>
          <button onClick={save} disabled={saving} className="text-xs text-blue-600 hover:text-blue-800 font-medium disabled:opacity-50">Save</button>
          <button onClick={() => { setEditing(false); setValue(String(balance)); }} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
        </span>
      ) : (
        <span className="flex items-center gap-2">
          <span className="font-medium">{fmt(balance)}</span>
          <button onClick={() => setEditing(true)} className="text-xs text-blue-500 hover:underline">Edit</button>
        </span>
      )}
    </div>
  );
}

function EstimateTab({ estimate, incomeType, onCarryforwardChange }: { estimate: DeductionsEstimate; incomeType: string; onCarryforwardChange: (value: number) => Promise<void> }) {
  const { combined } = estimate;
  const showEmp = incomeType !== "business";
  const showBiz = incomeType !== "employment";
  const showCombined = showEmp && showBiz;

  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-400">{estimate.period} · {estimate.date_range}</p>

      {/* Employment */}
      {showEmp && (
        <div className="space-y-3">
          <h3 className="font-semibold text-gray-700">Employment</h3>
          <EstimateSectionHeader label="Salary" section={estimate.employment} />
          <p className="text-xs text-gray-400">
            {estimate.gross_salary_source === "settings"
              ? "Salary from Tax Settings (YTD payslip figure). Work-related deductions applied."
              : "Work-related deductions on employment transactions."}
          </p>
          <SectionTable section={estimate.employment} emptyMsg="No employment expense transactions. Mark transactions as Employment in the Transactions page." />
        </div>
      )}

      {showCombined && <hr className="border-gray-100" />}

      {/* Business */}
      {showBiz && (
        <div className="space-y-3">
          <h3 className="font-semibold text-gray-700">Business</h3>
          <EstimateSectionHeader label="Business" section={estimate.business} />
          <p className="text-xs text-gray-400">Deductible business expenses against sales revenue.</p>
          <SectionTable section={estimate.business} emptyMsg="No business expense transactions. Mark transactions as Business in the Transactions page." />
        </div>
      )}

      {/* Combined — only when both income types are active */}
      {showCombined && (
        <>
          <hr className="border-gray-100" />
          <div className="bg-gray-50 rounded-xl border border-gray-100 p-5 space-y-4">
            <h3 className="font-semibold text-gray-700">Combined</h3>
            {combined.biz_is_loss ? (
              <div className="space-y-4">
                <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800">
                  <span className="mt-0.5">⚠</span>
                  <div className="space-y-1">
                    <p className="font-medium">Business is in a loss of {fmt(Math.abs(combined.biz_net))} — non-commercial loss rules apply (Div 35 ITAA 1997).</p>
                    <p>A business loss cannot automatically offset salary income this year. Two scenarios below depending on whether you pass an ATO test.</p>
                    {combined.ncl_tests_url && (
                      <a href={combined.ncl_tests_url} target="_blank" rel="noreferrer" className="underline hover:text-amber-900">ATO: Non-commercial loss tests →</a>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-white rounded-lg border border-gray-100 p-4 space-y-2">
                    <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">Loss deferred (carried forward)</p>
                    <div className="space-y-1">
                      <div className="flex justify-between text-sm"><span className="text-gray-500">Taxable income</span><span className="font-medium">{fmt(combined.ncl_applies!.taxable_income)}</span></div>
                      <div className="flex justify-between text-sm"><span className="text-gray-500">Est. tax payable</span><span className="font-bold text-red-500">{fmt(combined.ncl_applies!.income_tax)}</span></div>
                      {combined.payg_withheld > 0 && (
                        combined.ncl_applies!.tax_owing > 0
                          ? <div className="flex justify-between text-sm border-t border-gray-100 pt-1"><span className="text-gray-500">Est. to pay (after PAYG)</span><span className="font-bold text-red-500">{fmt(combined.ncl_applies!.tax_owing)}</span></div>
                          : <div className="flex justify-between text-sm border-t border-gray-100 pt-1"><span className="text-gray-500">Est. refund (after PAYG)</span><span className="font-bold text-green-600">{fmt(combined.ncl_applies!.tax_refund)}</span></div>
                      )}
                      <div className="flex justify-between text-sm border-t border-gray-100 pt-1"><span className="text-gray-500">New carryforward balance</span><span className="font-medium">{fmt(combined.ncl_applies!.carryforward_after)}</span></div>
                    </div>
                    <p className="text-xs text-gray-400">{combined.ncl_applies!.note}</p>
                  </div>
                  <div className="bg-white rounded-lg border border-gray-100 p-4 space-y-2">
                    <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">NCL test passed (offsets salary now)</p>
                    <div className="space-y-1">
                      <div className="flex justify-between text-sm"><span className="text-gray-500">Taxable income</span><span className="font-medium">{fmt(combined.ncl_exempt!.taxable_income)}</span></div>
                      <div className="flex justify-between text-sm"><span className="text-gray-500">Est. tax payable</span><span className="font-bold text-red-500">{fmt(combined.ncl_exempt!.income_tax)}</span></div>
                      {combined.payg_withheld > 0 && (
                        combined.ncl_exempt!.tax_owing > 0
                          ? <div className="flex justify-between text-sm border-t border-gray-100 pt-1"><span className="text-gray-500">Est. to pay (after PAYG)</span><span className="font-bold text-red-500">{fmt(combined.ncl_exempt!.tax_owing)}</span></div>
                          : <div className="flex justify-between text-sm border-t border-gray-100 pt-1"><span className="text-gray-500">Est. refund (after PAYG)</span><span className="font-bold text-green-600">{fmt(combined.ncl_exempt!.tax_refund)}</span></div>
                      )}
                      <div className="flex justify-between text-sm border-t border-gray-100 pt-1"><span className="text-gray-500">Carryforward balance</span><span className="font-medium">{fmt(combined.ncl_exempt!.carryforward_after)}</span></div>
                    </div>
                    <p className="text-xs text-gray-400">{combined.ncl_exempt!.note}</p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="grid grid-cols-3 gap-3 text-center">
                  <div>
                    <p className="text-xs text-gray-400">Salary taxable</p>
                    <p className="font-bold text-gray-800">{fmt(combined.salary_taxable)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Business net{(combined.carryforward_used ?? 0) > 0 ? " (after carryforward)" : ""}</p>
                    <p className="font-bold text-green-600">{fmt(combined.biz_net_after_carryforward ?? combined.biz_net)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Combined taxable</p>
                    <p className="font-bold text-gray-800">{fmt(combined.taxable_income ?? 0)}</p>
                  </div>
                </div>
                {(combined.carryforward_used ?? 0) > 0 && (
                  <p className="text-xs text-gray-500">
                    {fmt(combined.carryforward_used!)} of carried-forward business losses applied against this year&apos;s business profit of {fmt(combined.biz_net)}.
                    Remaining carryforward: {fmt(combined.carryforward_remaining!)}.
                  </p>
                )}
              </div>
            )}

            <div className="border-t border-gray-100 pt-3 space-y-1">
              <CarryforwardEditor balance={combined.carryforward_balance} onSave={onCarryforwardChange} />
              <p className="text-xs text-gray-400">
                Unused business losses deferred from previous years (Div 35 ITAA 1997). Update this from your prior-year tax return.
              </p>
            </div>
          </div>
        </>
      )}

      {/* Tax position — only for employment (PAYG applies to salary earners) */}
      {showEmp && <TaxPosition combined={combined} source={estimate.gross_salary_source} />}

      <p className="text-xs text-gray-400">Estimates only — consult a registered tax agent before lodging.</p>
    </div>
  );
}

function DeductionTable({ items }: { items: AITaxItem[] }) {
  if (items.length === 0) return <p className="text-xs text-gray-400 px-1">No transactions found for this section.</p>;
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 text-xs uppercase tracking-wide text-gray-500">
          <tr>
            <th className="px-4 py-3 text-left">Category</th>
            <th className="px-4 py-3 text-right">Spent</th>
            <th className="px-4 py-3 text-right">Rate</th>
            <th className="px-4 py-3 text-right">Deductible</th>
            <th className="px-4 py-3 text-left">Reasoning</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {items.map((item) => (
            <tr key={item.category} className="hover:bg-gray-50 align-top">
              <td className="px-4 py-3">
                <p className="font-medium text-gray-800 capitalize">{item.category.replace("_", " ")}</p>
                <p className="text-xs text-gray-400">{item.transaction_count} txns</p>
              </td>
              <td className="px-4 py-3 text-right text-gray-700">{fmt(item.total_spent)}</td>
              <td className="px-4 py-3 text-right">
                <span className={`text-xs font-medium px-2 py-0.5 rounded ${item.deductible_rate === 1 ? "bg-green-100 text-green-700" : item.deductible_rate >= 0.5 ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-500"}`}>
                  {Math.round(item.deductible_rate * 100)}%
                </span>
              </td>
              <td className="px-4 py-3 text-right font-medium text-green-700">{fmt(item.deductible_amount)}</td>
              <td className="px-4 py-3 max-w-xs">
                <p className="text-xs text-gray-600">{item.reasoning}</p>
                {item.ato_reference && <p className="text-xs text-gray-400 mt-0.5 italic">{item.ato_reference}</p>}
                {item.ato_urls.slice(0, 1).map((url) => (
                  <a key={url} href={url} target="_blank" rel="noreferrer"
                    className="text-xs text-blue-500 hover:underline mt-0.5 block truncate">{url}</a>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SectionSummary({ label, section }: { label: string; section: AITaxSection }) {
  return (
    <div className="grid grid-cols-3 gap-3 text-center text-sm">
      <div>
        <p className="text-xs text-gray-400">{label} Income</p>
        <p className="font-bold text-green-600">{fmt(section.income)}</p>
      </div>
      <div>
        <p className="text-xs text-gray-400">Deductible</p>
        <p className="font-bold text-blue-600">− {fmt(section.total_deductible)}</p>
      </div>
      <div>
        <p className="text-xs text-gray-400">Taxable</p>
        <p className="font-bold text-gray-800">{fmt(section.taxable_income)}</p>
      </div>
    </div>
  );
}

function AIEstimateTab({ result, incomeType }: { result: AITaxEstimate; incomeType: string }) {
  if (result.error) return <p className="text-red-500 text-sm">{result.error}</p>;
  const { salary, business, combined } = result;
  const showSalary = incomeType !== "business";
  const showBiz    = incomeType !== "employment";
  const showCombined = showSalary && showBiz;

  return (
    <div className="space-y-6">

      {/* Salary section */}
      {showSalary && (
        <div className="space-y-3">
          <h3 className="font-semibold text-gray-700">Salary Income</h3>
          <SectionSummary label="Salary" section={salary} />
          <p className="text-xs text-gray-400">Work-related deductions on personal (non-business) expenses.</p>
          <DeductionTable items={salary.items} />
        </div>
      )}

      {showCombined && <hr className="border-gray-100" />}

      {/* Business section */}
      {showBiz && (
        <div className="space-y-3">
          <h3 className="font-semibold text-gray-700">Business Income</h3>
          <SectionSummary label="Business" section={business} />
          <p className="text-xs text-gray-400">Deductible business expenses against sales revenue.</p>
          <DeductionTable items={business.items} />
        </div>
      )}

      {showCombined && <hr className="border-gray-100" />}

      {/* Combined / single-income tax summary */}
      <div className="bg-gray-50 rounded-xl border border-gray-100 p-5 space-y-4">
        <h3 className="font-semibold text-gray-700">{showCombined ? "Combined Tax Estimate" : "Tax Estimate"}</h3>

        {showCombined && combined.biz_is_loss ? (
          <div className="space-y-4">
            <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3">
              <span className="text-amber-500 mt-0.5">⚠</span>
              <div className="text-xs text-amber-800 space-y-1">
                <p className="font-medium">Business is in a loss of {fmt(Math.abs(combined.biz_net))} — non-commercial loss rules apply (Div 35 ITAA 1997).</p>
                <p>A business loss cannot automatically offset salary income. Two scenarios below depending on whether you pass an ATO test.</p>
                {combined.ncl_tests_url && (
                  <a href={combined.ncl_tests_url} target="_blank" rel="noreferrer" className="underline hover:text-amber-900">ATO: Non-commercial loss tests →</a>
                )}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="bg-white rounded-lg border border-gray-100 p-4 space-y-2">
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">NCL rules apply (loss deferred)</p>
                <div className="space-y-1">
                  <div className="flex justify-between text-sm"><span className="text-gray-500">Taxable income</span><span className="font-medium">{fmt(combined.ncl_applies!.taxable_income)}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-gray-500">Est. tax payable</span><span className="font-bold text-red-500">{fmt(combined.ncl_applies!.estimated_tax)}</span></div>
                  {combined.payg_withheld > 0 && (
                    combined.ncl_applies!.tax_owing > 0
                      ? <div className="flex justify-between text-sm border-t border-gray-100 pt-1"><span className="text-gray-500">Est. to pay (after PAYG)</span><span className="font-bold text-red-500">{fmt(combined.ncl_applies!.tax_owing)}</span></div>
                      : <div className="flex justify-between text-sm border-t border-gray-100 pt-1"><span className="text-gray-500">Est. refund (after PAYG)</span><span className="font-bold text-green-600">{fmt(combined.ncl_applies!.tax_refund)}</span></div>
                  )}
                </div>
                <p className="text-xs text-gray-400">{combined.ncl_applies!.note}</p>
              </div>
              <div className="bg-white rounded-lg border border-gray-100 p-4 space-y-2">
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide">NCL test passed (loss offsets salary)</p>
                <div className="space-y-1">
                  <div className="flex justify-between text-sm"><span className="text-gray-500">Taxable income</span><span className="font-medium">{fmt(combined.ncl_exempt!.taxable_income)}</span></div>
                  <div className="flex justify-between text-sm"><span className="text-gray-500">Est. tax payable</span><span className="font-bold text-red-500">{fmt(combined.ncl_exempt!.estimated_tax)}</span></div>
                  {combined.payg_withheld > 0 && (
                    combined.ncl_exempt!.tax_owing > 0
                      ? <div className="flex justify-between text-sm border-t border-gray-100 pt-1"><span className="text-gray-500">Est. to pay (after PAYG)</span><span className="font-bold text-red-500">{fmt(combined.ncl_exempt!.tax_owing)}</span></div>
                      : <div className="flex justify-between text-sm border-t border-gray-100 pt-1"><span className="text-gray-500">Est. refund (after PAYG)</span><span className="font-bold text-green-600">{fmt(combined.ncl_exempt!.tax_refund)}</span></div>
                  )}
                </div>
                <p className="text-xs text-gray-400">{combined.ncl_exempt!.note}</p>
              </div>
            </div>
          </div>
        ) : showCombined ? (
          <div className="grid grid-cols-3 gap-3 text-center">
            <div>
              <p className="text-xs text-gray-400">Salary taxable</p>
              <p className="text-lg font-bold text-gray-800">{fmt(combined.salary_taxable)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Business net profit</p>
              <p className="text-lg font-bold text-green-600">{fmt(combined.biz_net)}</p>
            </div>
            <div>
              <p className="text-xs text-gray-400">Combined taxable</p>
              <p className="text-lg font-bold text-gray-800">{fmt(combined.taxable_income!)}</p>
            </div>
            <div className="col-span-3 pt-1 border-t border-gray-100">
              <p className="text-xs text-gray-400">Est. tax payable</p>
              <p className="text-2xl font-bold text-red-500">{fmt(combined.estimated_tax!)}</p>
            </div>
            {combined.payg_withheld > 0 && (
              <>
                <div className="col-span-3 border-t border-gray-100 pt-1">
                  <p className="text-xs text-gray-400">PAYG withheld</p>
                  <p className="text-lg font-bold text-green-600">− {fmt(combined.payg_withheld)}</p>
                </div>
                <div className="col-span-3 border-t border-gray-100 pt-1">
                  {combined.tax_owing! > 0 ? (
                    <>
                      <p className="text-xs text-gray-400">Est. tax to pay</p>
                      <p className="text-2xl font-bold text-red-500">{fmt(combined.tax_owing!)}</p>
                    </>
                  ) : (
                    <>
                      <p className="text-xs text-gray-400">Est. tax refund</p>
                      <p className="text-2xl font-bold text-green-600">{fmt(combined.tax_refund!)}</p>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        ) : showSalary ? (
          /* Employment only */
          <div className="space-y-3 text-center">
            <div>
              <p className="text-xs text-gray-400">Salary taxable</p>
              <p className="text-lg font-bold text-gray-800">{fmt(combined.salary_taxable)}</p>
            </div>
            <div className="border-t border-gray-100 pt-3">
              <p className="text-xs text-gray-400">Est. tax payable</p>
              <p className="text-2xl font-bold text-red-500">{fmt(combined.estimated_tax!)}</p>
            </div>
            {combined.payg_withheld > 0 && (
              <>
                <div className="border-t border-gray-100 pt-3">
                  <p className="text-xs text-gray-400">PAYG withheld</p>
                  <p className="text-lg font-bold text-green-600">− {fmt(combined.payg_withheld)}</p>
                </div>
                <div className="border-t border-gray-100 pt-3">
                  {combined.tax_owing! > 0 ? (
                    <>
                      <p className="text-xs text-gray-400">Est. tax to pay</p>
                      <p className="text-2xl font-bold text-red-500">{fmt(combined.tax_owing!)}</p>
                    </>
                  ) : (
                    <>
                      <p className="text-xs text-gray-400">Est. tax refund</p>
                      <p className="text-2xl font-bold text-green-600">{fmt(combined.tax_refund!)}</p>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        ) : (
          /* Business only */
          <div className="space-y-3 text-center">
            <div>
              <p className="text-xs text-gray-400">Business net profit</p>
              <p className="text-lg font-bold text-green-600">{fmt(combined.biz_net)}</p>
            </div>
            <div className="border-t border-gray-100 pt-3">
              <p className="text-xs text-gray-400">Est. tax payable</p>
              <p className="text-2xl font-bold text-red-500">{fmt(combined.estimated_tax!)}</p>
            </div>
          </div>
        )}
        <p className="text-xs text-gray-400">{combined.tax_brackets}</p>
      </div>

      <p className="text-xs text-gray-400">{result.note}</p>
    </div>
  );
}

function RulesTab({ userType, incomeType }: { userType: string; incomeType: string }) {
  const showEmp = incomeType !== "business";
  const showBiz = incomeType !== "employment";
  const [section, setSection] = useState<"employment" | "business">(showEmp ? "employment" : "business");
  const [empRules, setEmpRules] = useState<DeductionRule[]>([]);
  const [bizRules, setBizRules] = useState<DeductionRule[]>([]);

  useEffect(() => {
    if (showEmp) api.getDeductionRules("individual_salary").then(setEmpRules);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (showBiz) api.getDeductionRules(userType).then(setBizRules);
  }, [userType]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-4">
      {showEmp && showBiz && (
        <div className="flex gap-1.5">
          <button
            onClick={() => setSection("employment")}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${section === "employment" ? "bg-gray-800 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"}`}
          >
            Employment
          </button>
          <button
            onClick={() => setSection("business")}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${section === "business" ? "bg-gray-800 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"}`}
          >
            Business
          </button>
        </div>
      )}
      {(section === "employment" || !showBiz) && showEmp && (
        <SingleRuleSet userType="individual_salary" rules={empRules} onRulesChange={setEmpRules} />
      )}
      {(section === "business" || !showEmp) && showBiz && (
        <SingleRuleSet userType={userType} rules={bizRules} onRulesChange={setBizRules} />
      )}
    </div>
  );
}

function SingleRuleSet({ userType, rules, onRulesChange }: { userType: string; rules: DeductionRule[]; onRulesChange: (r: DeductionRule[]) => void }) {
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
        <p className="text-sm text-gray-400">Deduction rates for <strong className="capitalize">{userType.replace(/_/g, " ")}</strong>. Edit rates or add custom categories.</p>
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

  async function handleAdd(e: React.SyntheticEvent) {
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
