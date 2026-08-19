# Product Requirement Document (PRD): AgBid Platform

## 1. Executive Overview
AgBid is a high-commitment, product-led B2B marketplace designed to eliminate opaque cooperative pricing and localized retail monopolies in agricultural inputs (crop protection, nutritionals, seeds). 

By leveraging **active-ingredient parity mapping** (CDMS/Agrian data engine) and **blind reverse auctions**, AgBid shifts buying leverage back to growers. By utilizing an **Option A Merchant of Record (Clearinghouse)** transaction model and grower **Must-Pick reserve pre-authorizations**, AgBid secures transactional lock-in and eliminates off-platform bypass leakage.

---

## 2. Core Technical Architecture
The platform is organized into four distinct modules:

```
                  ┌───────────────────────────────┐
                  │      Grower RFQ Console       │
                  └───────────────┬───────────────┘
                                  ▼
                  ┌───────────────────────────────┐
                  │   CDMS Parity Engine (SQL)    │
                  └───────────────┬───────────────┘
                                  ▼
         ┌────────────────────────┴────────────────────────┐
         ▼                                                 ▼
┌─────────────────────────────────┐               ┌─────────────────────────────────┐
│     Blind Auction Router        │               │    Clearinghouse Escrow         │
│  (Magic Link SMS/Email Dispatch)│               │  (John Deere Credit / Plaid ACH)│
└─────────────────────────────────┘               └─────────────────────────────────┘
```

---

## 3. Detailed Feature Specifications

### 3.1. CDMS / Agrian Active Ingredient Parity Engine
* **Goal:** Eradicate coop brand-name price obfuscation.
* **Mechanism:**
  * The system translates brand name products (e.g. "Roundup PowerMAX 3") to their primary active ingredient (e.g., "Glyphosate, 43.3%") and concentration.
  * The RFQ is broadcast to distributors labeled with the **active ingredient and volume requirement**, allowing them to bid generic equivalents.
* **Database Schema requirements:** `active_ingredients` parent table and a relational `chemical_brands` child table mapping EPA registration numbers.

### 3.2. Blind 48-Hour Reverse Auction Router (PLG Distribution Wedge)
* **Goal:** Enable friction-free distributor bidding while blocking price collusion.
* **Mechanism:**
  * When a grower broadcasts an RFQ, the system identifies registered distributors within a 150-mile radius.
  * **Magic Bidding Links:** Generates a secure, cryptographically signed URL containing a unique token (e.g., `agbid.app/bid/uuid-token`).
  * The router dispatches this link directly to distributor reps via SMS (Twilio) and Email (SendGrid).
  * Reps submit their blind bids (base price per gallon, freight/delivery cost, and optional adjuvant bundle) in a simple 10-second form without password registration.
  * Distributors cannot see competing bids, preventing cartel pricing behaviors.

### 3.3. Option A Clearinghouse Escrow & Invoicing
* **Goal:** Secure platform take-rate (2.5%) and eliminate disintermediation.
* **Mechanism:**
  * AgBid acts as the **Merchant of Record (Clearinghouse)**.
  * Grower pays AgBid via **Plaid/ACH transfer** or links their **John Deere Operating Line / Rabobank Credit Line** directly.
  * AgBid holds the funds in escrow, releases a secure freight-booking authorization to the distributor, and pays out the distributor (minus our commission) upon proof of delivered flatbed receipt.
  * Protecting Distributors: Because AgBid is the buyer on record, chemical manufacturers see AgBid purchasing at wholesale, protecting the distributor's regional license from MSRP retaliation.

### 3.4. Grower "Must-Pick" Reserve Gate
* **Goal:** Prevent growers from treating AgBid as a free pricing playground to beat down local coops offline.
* **Mechanism:**
  * Growers specify a **Target Reserve Price** during RFQ creation.
  * The grower's bank account or operating line is pre-authorized.
  * If a distributor submits a blind bid that meets or beats the grower's reserve price within 48 hours, the grower is **contractually obligated** to clear the deal.
  * Failure to select a matching bid triggers a $150 market-integrity fee.

---

## 4. Database Schema (PostgreSQL Model)

```sql
-- Core user tables
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    role VARCHAR(50) NOT NULL, -- 'grower', 'distributor', 'agronomist'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Active ingredient parity catalog (CDMS mock)
CREATE TABLE active_ingredients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    common_uses TEXT
);

CREATE TABLE chemical_brands (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_name VARCHAR(255) UNIQUE NOT NULL,
    active_ingredient_id UUID REFERENCES active_ingredients(id),
    epa_registration VARCHAR(100) UNIQUE NOT NULL,
    concentration_percentage NUMERIC(5,2) NOT NULL,
    default_adjuvant TEXT
);

-- RFQ transaction boards
CREATE TABLE rfqs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    grower_id UUID REFERENCES users(id),
    active_ingredient_id UUID REFERENCES active_ingredients(id),
    volume_gallons NUMERIC(10,2) NOT NULL,
    reserve_price_per_gal NUMERIC(10,2) NOT NULL,
    shipping_zip VARCHAR(20) NOT NULL,
    status VARCHAR(50) DEFAULT 'open', -- 'open', 'completed', 'cancelled'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Blind bids ledger
CREATE TABLE bids (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rfq_id UUID REFERENCES rfqs(id),
    distributor_id UUID REFERENCES users(id),
    price_per_gal NUMERIC(10,2) NOT NULL,
    freight_cost NUMERIC(10,2) DEFAULT 0.00,
    adjuvant_bundle_name VARCHAR(255),
    adjuvant_bundle_cost_per_gal NUMERIC(10,2) DEFAULT 0.00,
    delivery_days INT NOT NULL,
    magic_token VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 5. Non-Functional & Security Requirements
1. **Low-Bandwidth Mobile Optimization:** The frontend must load in under **1.5 seconds** on a 3G network. No bloated client-side JS bundles.
2. **Cryptographic Magic Link Safety:** Magic tokens must expire after 48 hours or upon successful submission of a bid.
3. **Plaid & Bank integration:** All financial data must conform to PCI-DSS standards.
