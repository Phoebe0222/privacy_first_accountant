"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

const INCOME_TYPES = [
  { value: "employment", label: "Employment only", description: "PAYG salary — work-related deductions apply, no BAS required." },
  { value: "business",   label: "Business only",   description: "Sole trader / company — business deductions and BAS (if GST registered)." },
  { value: "both",       label: "Both",             description: "Salary plus business income — employment and business deductions calculated separately." },
];

function fmt(n: number) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD" }).format(n);
}

export default function TaxSettingsPage() {
  const router = useRouter();
  const [incomeType, setIncomeType]       = useState("both");
  const [gstRegistered, setGstRegistered] = useState(false);
  const [grossSalary, setGrossSalary]     = useState("");
  const [paygWithheld, setPaygWithheld]   = useState("");
  const [privateHospitalCover, setPrivateHospitalCover] = useState(false);
  const [saved, setSaved]                 = useState(false);
  const [loading, setLoading]             = useState(true);

  useEffect(() => {
    api.getTaxProfile().then((p) => {
      setIncomeType(p.income_type);
      setGstRegistered(p.gst_registered);
      setGrossSalary(p.gross_salary > 0 ? String(p.gross_salary) : "");
      setPaygWithheld(p.payg_withheld > 0 ? String(p.payg_withheld) : "");
      setPrivateHospitalCover(p.private_hospital_cover);
    }).finally(() => setLoading(false));
  }, []);

  async function save() {
    await api.updateTaxProfile({
      income_type:    incomeType,
      gst_registered: gstRegistered,
      gross_salary:   parseFloat(grossSalary) || 0,
      payg_withheld:  parseFloat(paygWithheld) || 0,
      private_hospital_cover: privateHospitalCover,
    });
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
    router.refresh();
  }

  if (loading) return <p className="text-gray-400">Loading…</p>;

  const showBAS        = incomeType !== "employment";
  const showGST75kWarn = showBAS && !gstRegistered;
  const showSalaryFields = incomeType !== "business";

  return (
    <div className="space-y-8 max-w-xl">
      <div>
        <h2 className="text-2xl font-bold text-gray-800">Tax Settings</h2>
        <p className="text-sm text-gray-400 mt-1">
          These settings control which tax pages are relevant and how calculations are performed.
        </p>
      </div>

      {/* Income type */}
      <div className="space-y-3">
        <h3 className="font-semibold text-gray-700">Income Type</h3>
        <div className="space-y-2">
          {INCOME_TYPES.map(({ value, label, description }) => (
            <label key={value}
              className={`flex items-start gap-3 p-4 rounded-xl border cursor-pointer transition-colors ${
                incomeType === value ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-white hover:bg-gray-50"
              }`}>
              <input type="radio" name="income_type" value={value}
                checked={incomeType === value} onChange={() => setIncomeType(value)}
                className="mt-0.5" />
              <div>
                <p className="font-medium text-gray-800 text-sm">{label}</p>
                <p className="text-xs text-gray-500 mt-0.5">{description}</p>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* YTD payslip figures — shown for employment or both */}
      {showSalaryFields && (
        <div className="space-y-3">
          <div>
            <h3 className="font-semibold text-gray-700">Payslip YTD Figures</h3>
            <p className="text-xs text-gray-400 mt-0.5">
              Enter year-to-date totals from your latest payslip. When set, these override
              transaction-derived salary figures in the tax estimate.
            </p>
          </div>
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">YTD Gross Salary</label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
                <input
                  type="number"
                  min={0}
                  step={0.01}
                  value={grossSalary}
                  onChange={(e) => setGrossSalary(e.target.value)}
                  placeholder="0.00"
                  className="w-full border border-gray-200 rounded-lg pl-7 pr-3 py-2 text-sm"
                />
              </div>
              <p className="text-xs text-gray-400 mt-1">Total gross earnings before tax from your payslip.</p>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">YTD PAYG Withheld</label>
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
                <input
                  type="number"
                  min={0}
                  step={0.01}
                  value={paygWithheld}
                  onChange={(e) => setPaygWithheld(e.target.value)}
                  placeholder="0.00"
                  className="w-full border border-gray-200 rounded-lg pl-7 pr-3 py-2 text-sm"
                />
              </div>
              <p className="text-xs text-gray-400 mt-1">Total tax withheld by your employer (PAYG withholding).</p>
            </div>
            {grossSalary && paygWithheld && (
              <div className="bg-gray-50 rounded-lg p-3 text-xs text-gray-600 space-y-1">
                <div className="flex justify-between">
                  <span>Gross salary</span>
                  <span className="font-medium">{fmt(parseFloat(grossSalary) || 0)}</span>
                </div>
                <div className="flex justify-between text-gray-400">
                  <span>PAYG withheld</span>
                  <span>− {fmt(parseFloat(paygWithheld) || 0)}</span>
                </div>
                <div className="flex justify-between font-medium border-t border-gray-200 pt-1">
                  <span>Net pay</span>
                  <span>{fmt((parseFloat(grossSalary) || 0) - (parseFloat(paygWithheld) || 0))}</span>
                </div>
              </div>
            )}
          </div>
          <p className="text-xs text-gray-400">
            Or upload a payslip PDF on the{" "}
            <a href="/import" className="text-blue-500 hover:underline">Import page</a>{" "}
            to fill these automatically.
          </p>
        </div>
      )}

      {/* GST registration — only relevant when there is business income */}
      {showBAS && (
        <div className="space-y-3">
          <h3 className="font-semibold text-gray-700">GST Registration</h3>
          <label className={`flex items-start gap-3 p-4 rounded-xl border cursor-pointer transition-colors ${
            gstRegistered ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-white hover:bg-gray-50"
          }`}>
            <input type="checkbox" checked={gstRegistered}
              onChange={(e) => setGstRegistered(e.target.checked)} className="mt-0.5" />
            <div>
              <p className="font-medium text-gray-800 text-sm">Registered for GST</p>
              <p className="text-xs text-gray-500 mt-0.5">
                If registered, BAS estimation is enabled and income/expense amounts are calculated
                GST-exclusive for income tax purposes.
              </p>
            </div>
          </label>

          {showGST75kWarn && (
            <div className="flex items-start gap-2 bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800">
              <span className="mt-0.5">⚠</span>
              <span>
                If your annual business turnover reaches <strong>$75,000</strong>, you must register for GST.
                BAS is not shown while unregistered.
              </span>
            </div>
          )}
        </div>
      )}

      {/* Medicare Levy Surcharge — depends on private hospital cover */}
      <div className="space-y-3">
        <h3 className="font-semibold text-gray-700">Medicare Levy Surcharge</h3>
        <label className={`flex items-start gap-3 p-4 rounded-xl border cursor-pointer transition-colors ${
          privateHospitalCover ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-white hover:bg-gray-50"
        }`}>
          <input type="checkbox" checked={privateHospitalCover}
            onChange={(e) => setPrivateHospitalCover(e.target.checked)} className="mt-0.5" />
          <div>
            <p className="font-medium text-gray-800 text-sm">I have an appropriate level of private hospital cover</p>
            <p className="text-xs text-gray-500 mt-0.5">
              If checked, the Medicare Levy Surcharge (an extra 1–1.5% for high-income earners without
              private hospital cover) is not added to your tax estimate. Extras-only cover doesn&apos;t count.
            </p>
          </div>
        </label>
      </div>

      {/* Scenario summary */}
      <div className="bg-gray-50 border border-gray-100 rounded-xl p-4 space-y-1 text-xs text-gray-600">
        <p className="font-semibold text-gray-700 mb-2">Current scenario</p>
        {incomeType === "employment" && <p>• Work-related employment deductions • No BAS required • Tax = salary − employment deductions</p>}
        {incomeType !== "employment" && gstRegistered  && <p>• BAS enabled (GST quarterly reporting) • Income tax uses GST-exclusive amounts • NCL rules apply if business makes a loss</p>}
        {incomeType !== "employment" && !gstRegistered && <p>• No BAS • Income tax uses full amounts • $75k turnover threshold warning active • NCL rules apply if business makes a loss</p>}
        {incomeType === "both" && <p>• Employment deductions calculated separately from business deductions</p>}
      </div>

      <button onClick={save}
        className="bg-blue-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors">
        {saved ? "Saved ✓" : "Save Settings"}
      </button>
    </div>
  );
}
