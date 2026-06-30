import DashboardContent from "@/components/DashboardContent";

export default function DashboardPage() {
  return (
    <main className="mx-auto max-w-7xl px-4 py-10">
      <div className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-gray-900">
          LeadAI Dashboard
        </h1>
        <p className="mt-2 text-gray-600">
          Manage and enrich your sales leads.
        </p>
        <p className="mt-1 text-xs text-gray-500">
          ICP config: edit via PUT /icp-config (see README)
        </p>
      </div>

      <DashboardContent />
    </main>
  );
}
