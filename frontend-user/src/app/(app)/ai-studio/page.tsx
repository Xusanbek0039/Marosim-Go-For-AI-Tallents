"use client";

import { ShirtIcon, SparklesIcon } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";

import { PageTitle } from "@/components/shell";
import { Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { useAiStatus } from "@/lib/ai-tryon";

// The studio pulls in the Decart SDK (livekit-client); load it only on this page, never on the server.
const AiFashionStudio = dynamic(() => import("@/features/ai-studio/studio").then((m) => m.AiFashionStudio), {
  ssr: false,
  loading: () => <Skeleton className="aspect-[3/4] w-full rounded-3xl sm:aspect-video" />,
});

export default function AiStudioPage() {
  const status = useAiStatus();
  return (
    <>
      <PageTitle
        title="MarosimGo AI Fashion Studio"
        subtitle="Jonli kamerada kiyimni sun'iy intellekt yordamida o'zingizda ko'ring"
      />
      {status.error ? (
        <Card>
          <ErrorState error={status.error} onRetry={() => status.refetch()} />
        </Card>
      ) : status.isPending ? (
        <Skeleton className="aspect-[3/4] w-full rounded-3xl sm:aspect-video" />
      ) : !status.data.enabled ? (
        <Card>
          <EmptyState
            title="AI kiyib ko'rish hozircha yoqilmagan"
            description="Xizmat sozlanmagan. Hozircha kiyimlarni AR rejimida (kameradagi qatlamlar) kiyib ko'rishingiz mumkin."
            action={
              <Link href="/kiyib-korish">
                <Button variant="outline">
                  <ShirtIcon /> {"AR kiyib ko'rish"}
                </Button>
              </Link>
            }
          />
        </Card>
      ) : (
        <>
          <p className="flex items-center gap-2 text-xs text-muted-foreground">
            <SparklesIcon className="size-3.5" /> {"Natija Decart AI tomonidan jonli yaratiladi; sifat internet tezligiga bog'liq."}
          </p>
          <AiFashionStudio status={status.data} />
        </>
      )}
    </>
  );
}
