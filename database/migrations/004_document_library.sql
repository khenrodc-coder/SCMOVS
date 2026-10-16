-- Phase 6D migration. Run ONCE on a database created BEFORE Phase 6D.
-- (Fresh installs already get these columns from the updated schema.sql.)
--
--   mysql -u root -p scmovs < database/migrations/004_document_library.sql

USE scmovs;

-- A short description and a category, so council documents can be organised and filtered.
-- 'financial' is reserved for receipts and budget supporting files: they belong to the finance
-- records and never appear in the document library.
ALTER TABLE documents
    ADD COLUMN description VARCHAR(500) NULL AFTER title,
    ADD COLUMN category ENUM('report','minutes','proposal','financial','memo','other') NOT NULL DEFAULT 'other' AFTER description,
    ADD INDEX idx_documents_library (council_id, is_archived, category);

-- Existing receipts and budget supporting files become 'financial'.
UPDATE documents SET category = 'financial'
WHERE id IN (SELECT supporting_document_id FROM budgets WHERE supporting_document_id IS NOT NULL)
   OR id IN (SELECT receipt_document_id FROM expenses WHERE receipt_document_id IS NOT NULL)
   OR title IN ('Budget document', 'Expense document')
   OR title LIKE 'Receipt:%'
   OR title LIKE 'Budget support:%';