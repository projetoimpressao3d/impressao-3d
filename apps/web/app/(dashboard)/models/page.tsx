import { redirect } from "next/navigation";
import { createClient, createAdminClient } from "@/lib/supabase/server";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

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
  const { data: profile } = await admin
    .from("profiles")
    .select("plan")
    .eq("id", user.id)
    .single();

  const plan = (profile?.plan ?? "free") as "free" | "pro";

  return <WorkspaceShell userEmail={user.email ?? ""} userPlan={plan} />;
}
