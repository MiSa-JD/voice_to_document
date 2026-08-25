import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import openapiTS, { astToString, COMMENT_HEADER } from 'openapi-typescript';

const schemaPath = fileURLToPath(
  new URL('../../openapi.json', import.meta.url),
);
const outputPath = fileURLToPath(
  new URL('../src/api/schema.d.ts', import.meta.url),
);
const schema = JSON.parse(await readFile(schemaPath, 'utf8'));
const output = COMMENT_HEADER + astToString(await openapiTS(schema));

if (process.argv.includes('--write')) {
  await writeFile(outputPath, output, 'utf8');
} else if ((await readFile(outputPath, 'utf8').catch(() => '')) !== output) {
  throw new Error('OpenAPI TypeScript types differ; run `make api-schema`.');
}
