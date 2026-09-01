import { request } from "../request";

export interface SuperExpertPlatformCommand {
  installation_id: string;
  contract_version: "1";
  idempotency_key: string;
  arguments: Record<string, unknown>;
}

export const superExpertPlatformApi = {
  command: (capability: string, command: SuperExpertPlatformCommand) =>
    request(
      `/super-expert-platform/commands/${encodeURIComponent(capability)}`,
      {
        method: "POST",
        body: JSON.stringify(command),
      },
    ),
};
