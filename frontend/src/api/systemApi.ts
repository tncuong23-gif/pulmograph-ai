import { apiRequest, USE_MOCK_API } from "./client";
import { mockService } from "../mocks/mockService";
import type { SystemStatus } from "../types";
export const systemApi = {
  getStatus: (): Promise<SystemStatus> =>
    USE_MOCK_API ? mockService.status() : apiRequest("/api/v1/status"),
};
