/* Embedded sample data so the "Load sample" button works offline (no fetch/CORS). */
(function (root) {
  "use strict";
  const SAMPLE = {};

  SAMPLE.policies = `cedant,policy_id,insured_name,line_of_business,peril,inception_date,expiry_date,sum_insured,currency,gross_premium,ceded_share
Alpha Mutual,AL-001,Northwind Logistics,Property,Fire,2025-01-01,2025-12-31,4500000,USD,18000,0.60
Alpha Mutual,AL-002,Harbor Freight Co,Marine,Cargo,2025-02-01,2026-01-31,3200000,USD,12800,0.60
Alpha Mutual,AL-003,Summit Chemicals,Liability,PublicLiability,2025-03-01,2026-02-28,5000000,USD,20000,0.55
Alpha Mutual,AL-004,Ridgefield Retail,Property,Fire,2025-01-15,2025-12-15,2800000,USD,11200,0.60
Alpha Mutual,AL-005,Coastal Foods,Property,Storm,2025-04-01,2025-09-01,30000000,USD,60000,0.60
Alpha Mutual,AL-006,Maple Motors,Motor,Collision,2025-05-01,2026-04-30,750000,USD,3000,0.50
Beta Insurance,BE-001,Quantech Ltd,Property,Fire,2025-01-01,2025-12-31,4200000,USD,16800,0.40
Beta Insurance,BE-002,Lakeside Hotels,Liability,PublicLiability,2025-02-15,2026-02-14,3600000,USD,14400,0.40
Beta Insurance,BE-003,Orion Shipping,Marine,Cargo,2025-03-01,2026-02-28,5100000,USD,20400,0.45
Beta Insurance,BE-004,Brightpath Schools,Property,Fire,2025-06-01,2025-05-01,2900000,USD,11600,0.40
Beta Insurance,BE-005,Vertex Manufacturing,Property,Fire,2025-01-01,2025-12-31,,USD,17000,0.40
Beta Insurance,BE-006,Silverline Transport,Motor,Collision,2025-04-01,2026-03-31,690000,USD,2760,0.40
Gamma Re,GA-001,Atlantic Pharma,Liability,ProductsLiability,2025-01-01,2025-12-31,6200000,EUR,24000,0.50
Gamma Re,GA-002,Northgate Utilities,Property,Fire,2025-02-01,2026-01-31,4800000,USD,19200,0.50
Gamma Re,GA-003,Pinnacle Foods,Marine,Cargo,2025-03-15,2026-03-14,3400000,USD,13600,0.45
Gamma Re,GA-004,Cedar Bank,Liability,ProfessionalIndemnity,2025-05-01,2026-04-30,7100000,USD,28400,0.50
Gamma Re,GA-005,Riverstone Farms,Property,Storm,2025-01-01,2025-12-31,2500000,USD,10000,0.45
Delta P&C,DE-001,Metro Construction,Property,Fire,2025-01-01,2025-12-31,3900000,USD,15600,0.40
Delta P&C,DE-002,Fairview Hospitals,Liability,PublicLiability,2025-02-01,2026-01-31,5500000,USD,22000,0.45
Delta P&C,DE-003,Bluewave Retail,Property,Fire,2025-03-01,2026-02-28,2700000,USD,5400,0.40
Delta P&C,DE-004,Stonebridge Logistics,Marine,Cargo,2025-04-01,2026-03-31,3100000,USD,12400,0.40
Delta P&C,DE-005,Hillcrest Auto,Motor,Collision,2025-05-01,2026-04-30,720000,USD,2880,0.40
`;

  SAMPLE.claims = `cedant,claim_id,policy_id,date_of_loss,reported_date,paid_amount,outstanding_amount,currency,cause_of_loss,insured_name
Alpha Mutual,AL-C01,AL-001,2025-03-10,2025-03-25,70000,20000,USD,Fire,Northwind Logistics
Alpha Mutual,AL-C02,AL-003,2025-06-01,2025-06-20,40000,0,USD,ThirdPartyInjury,Summit Chemicals
Alpha Mutual,AL-C03,AL-005,2025-07-15,2025-07-30,80000,40000,USD,Storm,Coastal Foods
Alpha Mutual,AL-C04,AL-002,2025-05-05,2025-11-20,30000,0,USD,CargoDamage,Harbor Freight Co
Alpha Mutual,AL-C05,AL-004,2025-08-01,2025-08-15,20000,5000,USD,Fire,Ridgefield Retail
Alpha Mutual,AL-C06,AL-001,2025-09-12,2025-09-20,25000,0,USD,Fire,Northwind Logistics
Beta Insurance,BE-C07,BE-001,2025-09-12,2025-09-22,25000,0,USD,Fire,Northwind Logistics
Beta Insurance,BE-C01,BE-003,2025-04-01,2025-04-18,12000,0,USD,CargoDamage,Orion Shipping
Beta Insurance,BE-C02,BE-002,2025-07-01,2025-07-15,8000,2000,USD,SlipAndFall,Lakeside Hotels
Beta Insurance,BE-C03,BE-006,2025-08-10,2025-08-25,4000,0,USD,Collision,Silverline Transport
Gamma Re,GA-C01,GA-004,2025-05-20,2025-06-10,18000,6000,USD,ProfessionalNegligence,Cedar Bank
Gamma Re,GA-C02,GA-002,2025-06-15,2025-07-01,12000,0,USD,Fire,Northgate Utilities
Gamma Re,GA-C03,GA-003,2025-09-01,2025-09-15,7000,2000,USD,CargoDamage,Pinnacle Foods
Delta P&C,DE-C01,DE-002,2025-03-20,2025-04-05,15000,4000,USD,ThirdPartyInjury,Fairview Hospitals
Delta P&C,DE-C02,DE-001,2025-07-25,2025-08-10,9000,0,USD,Fire,Metro Construction
Delta P&C,DE-C03,DE-005,2025-08-30,2025-09-12,3500,0,USD,Collision,Hillcrest Auto
Delta P&C,DE-C04,DE-003,2025-10-01,2025-10-15,6000,1500,USD,Fire,Bluewave Retail
`;

  SAMPLE.slip = `==============================================================
        REINSURANCE PLACING SLIP  (FACULTATIVE / TREATY)
==============================================================

Reinsured / Cedant :  Alpha Mutual Insurance
Cedant Reference   :  ALPHA-PROP-2025
Contract Period    :  01/01/2025 to 31/12/2025 (12 months)
Line / Class       :  Property - Fire & Allied Perils
Territory          :  United States
Basis of Cover     :  Occurrence
Cession            :  45% of each risk
Layer Attachment   :  USD 1,000,000 xs USD 500,000
Layer Limit        :  USD 4,000,000
Reinsurance Prem.  :  USD 42,000 (100% basis)
Reinsurer Share    :  25%
Broker             :  Meridian Re Brokers
Slip Reference     :  MRB-2025-0447
Lead Underwriter   :  J. Whitfield
Slip Signed Date   :  18/12/2024

Notes: Subject to survey of risks over USD 3,000,000.
==============================================================
`;

  if (typeof module !== "undefined" && module.exports) module.exports = SAMPLE;
  if (typeof window !== "undefined") window.SAMPLE = SAMPLE;
  if (root) root.SAMPLE = SAMPLE;
})(typeof globalThis !== "undefined" ? globalThis : this);
