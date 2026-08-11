import { z } from "zod";

const componentHealthSchema = z.strictObject({
  name: z.enum(["PostgreSQL", "Valkey"]),
  status: z.enum(["ok", "unavailable"]),
});

const readinessSchema = z.strictObject({
  components: z.array(componentHealthSchema).readonly(),
  environment: z.enum(["development", "test", "production"]),
  service: z.literal("api"),
  status: z.enum(["ready", "degraded"]),
  version: z.string().min(1),
});

export type ComponentHealth = z.infer<typeof componentHealthSchema>;
export type Readiness = z.infer<typeof readinessSchema>;

export const parseReadiness = (input: unknown): Readiness => readinessSchema.parse(input);
