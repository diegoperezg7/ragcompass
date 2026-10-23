# Service Desk Onboarding Handbook

Welcome to the service desk of Halden Instruments. This handbook explains how tickets flow, which
tools you will use and what we expect from you in your first month. Keep it open during your first
shifts; most questions new colleagues ask are answered here.

## How a ticket flows

Every request from a customer becomes a ticket. A ticket starts in the triage queue, where the
on-call agent reads it, sets a priority and assigns a product. Tickets about the HX-200 bench
calibrator go to the instruments team; tickets about invoices go to billing. A ticket is only closed
when the customer confirms that the problem is solved or after five working days without an answer.

1. Read the ticket and check the serial number against the asset register.
2. Set the priority using the table below.
3. Assign the product and the team.
4. Reply to the customer within the first-response target.

| Priority | Meaning | First response | Example |
|---|---|---|---|
| P1 | Safety issue or production stopped | 4 hours | Burnt smell from an HX-200 |
| P2 | Instrument unusable, workaround exists | 1 working day | Error E-415 on the output |
| P3 | Question or minor fault | 3 working days | How to export the service log |

## Tools

We work with three tools. The ticketing system holds the conversation with the customer. The asset
register tells you which instruments a customer owns, when they were last verified and which
contract covers them. The knowledge base contains procedures written by the instruments team; link
the relevant article in your reply instead of copying it, so customers always see the latest version.

### Writing a good reply

A good reply restates the problem in one sentence, gives the next step and says when the customer
will hear from us again. Avoid internal codes in replies unless the customer used them first. When
you ask for information, ask for everything you need in one message: the serial number, the error
code shown on the status screen and the firmware version.

- Use the customer's name and the ticket number in the subject.
- Quote part numbers exactly, for example HX-FAN-118, never "the fan".
- Never promise a delivery date that the warehouse has not confirmed.

## Escalation

Escalate a ticket to the service lead when a safety issue is reported, when a customer asks for a
refund above CHF 2,000, or when the same instrument comes back with the same fault within ninety
days. Escalation does not mean handing over the ticket: you stay the contact for the customer and
the lead helps you decide.

## Your first month

During your first week you will shadow a senior agent and answer P3 tickets only. In the second week
you will take P2 tickets with a reviewer. From the third week you join the on-call rotation for
triage. At the end of the month we review ten of your tickets together and agree on what to work on.

```bash
# Export your open tickets for the weekly review
desk export --assignee me --status open --format csv > my-tickets.csv
```
