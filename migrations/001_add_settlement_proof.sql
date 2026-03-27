-- Migration: Add settlement proof columns
-- Run this in Supabase SQL Editor (Database -> SQL Editor)
-- Required for settlement proof upload feature

ALTER TABLE expenses
  ADD COLUMN IF NOT EXISTS settlement_proof_url TEXT,
  ADD COLUMN IF NOT EXISTS settled_by TEXT,
  ADD COLUMN IF NOT EXISTS settled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS settlement_note TEXT;

-- Index on status for faster filtering
CREATE INDEX IF NOT EXISTS idx_expenses_status ON expenses(status);

COMMENT ON COLUMN expenses.settlement_proof_url IS 'URL to settlement payment screenshot in Supabase Storage (receipts/settlements/)';
COMMENT ON COLUMN expenses.settled_by IS 'Name of the parent who submitted the settlement proof';
COMMENT ON COLUMN expenses.settled_at IS 'UTC timestamp when the settlement was confirmed';
COMMENT ON COLUMN expenses.settlement_note IS 'Optional note (e.g. Venmo @username, $42.50)';
