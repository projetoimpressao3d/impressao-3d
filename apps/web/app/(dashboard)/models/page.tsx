import { redirect } from "next/navigation";
import { createClient, createAdminClient } from "@/lib/supabase/server";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import type { BuildPlate, Model } from "@/types/database";

export const metadata = { title: "Workspace 3D" };

export default async function ModelsPage() {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const admin = createAdminClient();
  const [profileResult, platesResult, modelsResult, subscriptionResult] =
    await Promise.all([
      admin.from("profiles").select("plan").eq("id", user.id).single(),
      supabase
        .from("build_plates")
        .select("*")
        .order("is_default", { ascending: false })
        .order("created_at", { ascending: true }),
      supabase
        .from("models")
        .select("*")
        .order("created_at", { ascending: false }),
      supabase
        .from("subscriptions")
        .select("id")
        .eq("user_id", user.id)
        .eq("status", "active")
        .limit(1)
        .single(),
    ]);

  const plan = (profileResult.data?.plan ?? "free") as "free" | "pro";
  const hasSubscription = !!subscriptionResult.data || plan === "pro";
  const initialPlates = (platesResult.data ?? []) as BuildPlate[];
  const initialModels = (modelsResult.data ?? []) as Model[];

  return (
    <WorkspaceShell
      userEmail={user.email ?? ""}
      userPlan={plan}
      hasSubscription={hasSubscription}
      initialPlates={initialPlates}
      initialModels={initialModels}
    />
  );
}
