"use client";
import { useEffect, useRef, useState } from "react";
import { api, EmailAccount } from "@/lib/api";

const GMAIL_IMAP = { host: "imap.gmail.com", port: 993 };
const OUTLOOK_IMAP = { host: "outlook.office365.com", port: 993 };

export default function ImportPage() {
  const [accounts, setAccounts] = useState<EmailAccount[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [syncing, setSyncing] = useState<number | null>(null);
  const [reimporting, setReimporting] = useState<number | null>(null);
  const [syncResult, setSyncResult] = useState<string>("");
  const [form, setForm] = useState({
    name: "", email: "", imap_host: "imap.gmail.com", imap_port: 993, username: "", password: "",
  });
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState<string>("");
  const fileRef = useRef<HTMLInputElement>(null);
  const csvRef = useRef<HTMLInputElement>(null);
  const [csvUploading, setCsvUploading] = useState(false);
  const [csvResult, setCsvResult] = useState<string>("");
  const [csvType, setCsvType] = useState<"bank" | "supplier">("bank");

  function loadAccounts() {
    api.getEmailAccounts().then(setAccounts).catch(() => {});
  }

  useEffect(() => { loadAccounts(); }, []);

  async function handleAddAccount(e: React.FormEvent) {
    e.preventDefault();
    await api.addEmailAccount(form);
    setShowForm(false);
    setForm({ name: "", email: "", imap_host: "imap.gmail.com", imap_port: 993, username: "", password: "" });
    loadAccounts();
  }

  async function handleSync(id: number, reimport = false) {
    reimport ? setReimporting(id) : setSyncing(id);
    setSyncResult("");
    try {
      const r = await api.syncEmailAccount(id, 30, reimport);
      setSyncResult(`Done: ${r.added} new transactions added, ${r.skipped} skipped.`);
      loadAccounts();
    } catch (e: unknown) {
      setSyncResult(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSyncing(null);
      setReimporting(null);
    }
  }

  async function handleCsvUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsvUploading(true);
    setCsvResult("");
    try {
      const r = await api.uploadCsv(file, csvType);
      const label = csvType === "bank" ? "bank statement" : "supplier/processor";
      setCsvResult(`Done: ${r.added} transactions imported from ${label}, ${r.skipped} rows skipped.`);
    } catch (err: unknown) {
      setCsvResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCsvUploading(false);
      if (csvRef.current) csvRef.current.value = "";
    }
  }

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadResult("");
    try {
      const r = await api.uploadFile(file);
      const t = r.transaction;
      setUploadResult(`Extracted: ${t.vendor} — ${t.type} of $${t.amount} on ${t.date} (${t.category})`);
    } catch (err: unknown) {
      setUploadResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <div className="space-y-10 max-w-2xl">
      <h2 className="text-2xl font-bold text-gray-800">Import</h2>

      {/* Email accounts */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-700">Email Accounts</h3>
          <button
            onClick={() => setShowForm(!showForm)}
            className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition-colors"
          >
            + Add Account
          </button>
        </div>

        {showForm && (
          <form onSubmit={handleAddAccount} className="bg-white border border-gray-100 rounded-xl p-6 space-y-4 shadow-sm">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Account name</label>
                <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="e.g. Work Gmail" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Email address</label>
                <input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              </div>
            </div>
            <div className="flex gap-3">
              <button type="button" onClick={() => setForm({ ...form, ...GMAIL_IMAP })}
                className="text-xs border border-gray-200 rounded px-3 py-1.5 hover:bg-gray-50">Gmail</button>
              <button type="button" onClick={() => setForm({ ...form, ...OUTLOOK_IMAP })}
                className="text-xs border border-gray-200 rounded px-3 py-1.5 hover:bg-gray-50">Outlook</button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs text-gray-500 mb-1 block">IMAP host</label>
                <input required value={form.imap_host} onChange={(e) => setForm({ ...form, imap_host: e.target.value })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              </div>
              <div>
                <label className="text-xs text-gray-500 mb-1 block">Port</label>
                <input required type="number" value={form.imap_port} onChange={(e) => setForm({ ...form, imap_port: Number(e.target.value) })}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              </div>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Username (usually your email)</label>
              <input required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">App password</label>
              <input required type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
              <p className="text-xs text-gray-400 mt-1">Gmail: use an App Password, not your main password.</p>
            </div>
            <div className="flex gap-3 pt-2">
              <button type="submit" className="bg-blue-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-blue-700">Save</button>
              <button type="button" onClick={() => setShowForm(false)} className="text-sm text-gray-500 hover:text-gray-700">Cancel</button>
            </div>
          </form>
        )}

        {accounts.length === 0 && !showForm && (
          <p className="text-gray-400 text-sm">No email accounts connected yet.</p>
        )}
        <div className="space-y-3">
          {accounts.map((a) => (
            <div key={a.id} className="bg-white border border-gray-100 rounded-xl p-4 flex items-center justify-between shadow-sm">
              <div>
                <p className="font-medium text-gray-800">{a.name}</p>
                <p className="text-sm text-gray-400">{a.email} · {a.imap_host}</p>
                {a.last_synced && <p className="text-xs text-gray-300 mt-0.5">Last synced: {new Date(a.last_synced).toLocaleString()}</p>}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleSync(a.id)}
                  disabled={syncing === a.id || reimporting === a.id}
                  className="text-sm bg-gray-800 text-white px-4 py-2 rounded-lg hover:bg-gray-700 disabled:opacity-50"
                >
                  {syncing === a.id ? "Syncing…" : "Sync (30 days)"}
                </button>
                <button
                  onClick={() => handleSync(a.id, true)}
                  disabled={syncing === a.id || reimporting === a.id}
                  className="text-sm border border-gray-300 text-gray-600 px-4 py-2 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  {reimporting === a.id ? "Re-importing…" : "Re-import"}
                </button>
                <button onClick={() => api.deleteEmailAccount(a.id).then(loadAccounts)}
                  className="text-sm text-gray-300 hover:text-red-500 px-2">✕</button>
              </div>
            </div>
          ))}
        </div>
        {syncResult && (
          <p className={`text-sm ${syncResult.startsWith("Error") ? "text-red-500" : "text-green-600"}`}>{syncResult}</p>
        )}
      </section>

      {/* CSV upload */}
      <section className="space-y-4">
        <h3 className="text-lg font-semibold text-gray-700">CSV Import</h3>
        <p className="text-sm text-gray-400">Upload any CSV export — the AI will detect the columns automatically.</p>

        <div className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm space-y-3">
          <p className="text-sm font-medium text-gray-700">What type of CSV is this?</p>
          <div className="flex gap-3">
            <button
              onClick={() => setCsvType("bank")}
              className={`flex-1 text-sm px-4 py-2.5 rounded-lg border transition-colors ${
                csvType === "bank"
                  ? "bg-blue-600 text-white border-blue-600"
                  : "border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
            >
              🏦 Bank Statement
              <span className="block text-xs mt-0.5 opacity-75">Primary record — used in BAS & deductions</span>
            </button>
            <button
              onClick={() => setCsvType("supplier")}
              className={`flex-1 text-sm px-4 py-2.5 rounded-lg border transition-colors ${
                csvType === "supplier"
                  ? "bg-blue-600 text-white border-blue-600"
                  : "border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
            >
              🏪 Supplier / Processor
              <span className="block text-xs mt-0.5 opacity-75">Stripe, PayPal, Shopify, etc. — reconciliation only</span>
            </button>
          </div>
        </div>

        <div className="bg-white border-2 border-dashed border-gray-200 rounded-xl p-8 text-center">
          <input ref={csvRef} type="file" accept=".csv,.xlsx,.xls" onChange={handleCsvUpload} className="hidden" id="csv-upload" />
          <label htmlFor="csv-upload"
            className="cursor-pointer bg-blue-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-blue-700 transition-colors">
            {csvUploading ? "Processing…" : "Choose CSV"}
          </label>
        </div>
        {csvResult && (
          <p className={`text-sm ${csvResult.startsWith("Error") ? "text-red-500" : "text-green-600"}`}>{csvResult}</p>
        )}
      </section>

      {/* File upload */}
      <section className="space-y-4">
        <h3 className="text-lg font-semibold text-gray-700">Upload PDF or Receipt Photo</h3>
        <div className="bg-white border-2 border-dashed border-gray-200 rounded-xl p-8 text-center">
          <p className="text-gray-400 text-sm mb-4">PDF invoices, receipt images (JPG, PNG, WEBP)</p>
          <input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.webp"
            onChange={handleFileUpload} className="hidden" id="file-upload" />
          <label htmlFor="file-upload"
            className="cursor-pointer bg-blue-600 text-white px-5 py-2 rounded-lg text-sm hover:bg-blue-700 transition-colors">
            {uploading ? "Processing…" : "Choose File"}
          </label>
        </div>
        {uploadResult && (
          <p className={`text-sm ${uploadResult.startsWith("Error") ? "text-red-500" : "text-green-600"}`}>{uploadResult}</p>
        )}
      </section>
    </div>
  );
}
