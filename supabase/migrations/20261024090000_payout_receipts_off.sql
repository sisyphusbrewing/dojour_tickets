-- Sam (Oct 24 2026): no emailed receipts when a comic is paid. Lines start
-- with receipt_wanted off; payout_mail.py still sends get-paid links.
alter table public.payouts alter column receipt_wanted set default false;
update public.payouts set receipt_wanted = false where receipt_sent_at is null;
