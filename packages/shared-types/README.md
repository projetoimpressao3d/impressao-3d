# shared-types

Tipos TypeScript e modelos Pydantic compartilhados entre `/apps/web` e `/apps/mesh-service`.

> **Fase 1:** Este pacote está vazio intencionalmente. Os contratos de API serão adicionados
> conforme as funcionalidades forem implementadas (Fase 2+).

## Estrutura futura

```
packages/shared-types/
  src/
    api/
      health.ts         # contrato do endpoint /health
      split.ts          # contrato de split sessions
      models.ts         # contrato de modelos 3D
    pydantic/           # modelos Pydantic espelhados (gerados ou mantidos manualmente)
  package.json
  tsconfig.json
```
