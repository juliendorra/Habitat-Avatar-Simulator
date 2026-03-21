
import { parse } from "https://deno.land/std@0.208.0/dotenv/mod.ts";

async function pushSecrets() {
    try {
        // 1. Check if authenticated
        const authStatus = new Deno.Command("gh", {
            args: ["auth", "status"],
            stdout: "null",
            stderr: "null",
        });
        const authOutput = await authStatus.output();

        if (authOutput.code !== 0) {
            console.log("⚠️  You are not logged into GitHub CLI.");
            console.log("� Initiating login flow...");

            const loginCmd = new Deno.Command("gh", {
                args: ["auth", "login"],
                stdin: "inherit",
                stdout: "inherit",
                stderr: "inherit",
            });

            const loginProcess = loginCmd.spawn();
            const loginStatus = await loginProcess.status;

            if (!loginStatus.success) {
                console.error("❌ Login failed. Exiting.");
                Deno.exit(1);
            }
            console.log("✅ Login successful!");
        }

        // 2. Identify repository
        const repoView = new Deno.Command("gh", {
            args: ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            stdout: "piped",
            stderr: "piped",
        });
        const repoOutput = await repoView.output();
        if (repoOutput.code !== 0) {
            console.error("❌ Could not determine GitHub repository.");
            console.error("👉 Ensure you are in a git repository with a remote 'origin'.");
            console.error(new TextDecoder().decode(repoOutput.stderr));
            Deno.exit(1);
        }
        const repoName = new TextDecoder().decode(repoOutput.stdout).trim();
        console.log(`🔒 Preparing to push secrets to: ${repoName}`);

        // 3. Read secrets
        const text = await Deno.readTextFile(".envprod");
        const env = parse(text);

        if (Object.keys(env).length === 0) {
            console.log("No secrets found in .envprod");
            return;
        }

        console.log(`Found ${Object.keys(env).length} secrets.`);

        for (const [key, value] of Object.entries(env)) {
            console.log(`Setting secret ${key}...`);

            const command = new Deno.Command("gh", {
                args: ["secret", "set", key],
                stdin: "piped",
                stdout: "piped",
                stderr: "piped",
            });

            const child = command.spawn();

            const writer = child.stdin.getWriter();
            await writer.write(new TextEncoder().encode(value));
            await writer.releaseLock();
            await child.stdin.close();

            const { code, stderr } = await child.output();

            if (code !== 0) {
                const errorText = new TextDecoder().decode(stderr);
                console.error(`Failed to set ${key}: ${errorText}`);
            } else {
                console.log(`✓ Secret ${key} set successfully.`);
            }
        }
        console.log("✅ All secrets pushed successfully.");

    } catch (error) {
        if (error instanceof Deno.errors.NotFound) {
            console.error("Error: .envprod file not found.");
        } else {
            console.error("An error occurred:", error);
        }
        Deno.exit(1);
    }
}

if (import.meta.main) {
    pushSecrets();
}
