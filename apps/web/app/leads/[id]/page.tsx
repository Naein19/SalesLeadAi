import Link from "next/link";

import LeadDetailContent from "@/components/LeadDetailContent";

interface LeadDetailPageProps {
  params: { id: string };
}

export default function LeadDetailPage({ params }: LeadDetailPageProps) {
  return (
    <main className="mx-auto max-w-4xl px-4 py-10">
      <Link
        href="/"
        className="mb-6 inline-block text-sm text-blue-600 hover:text-blue-800"
      >
        &larr; Back to dashboard
      </Link>

      <LeadDetailContent id={params.id} />
    </main>
  );
}
