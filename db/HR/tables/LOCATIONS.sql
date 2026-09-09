CREATE TABLE "HR"."LOCATIONS" 
   (	"LOCATION_ID" NUMBER(4,0), 
	"STREET_ADDRESS" VARCHAR2(40) COLLATE "USING_NLS_COMP", 
	"POSTAL_CODE" VARCHAR2(12) COLLATE "USING_NLS_COMP", 
	"CITY" VARCHAR2(30) COLLATE "USING_NLS_COMP" CONSTRAINT "LOC_CITY_NN" NOT NULL ENABLE, 
	"STATE_PROVINCE" VARCHAR2(25) COLLATE "USING_NLS_COMP", 
	"COUNTRY_ID" CHAR(2) COLLATE "USING_NLS_COMP", 
	 CONSTRAINT "LOC_C_ID_FK" FOREIGN KEY ("COUNTRY_ID")
	  REFERENCES "HR"."COUNTRIES" ("COUNTRY_ID") ENABLE
   )  DEFAULT COLLATION "USING_NLS_COMP" ;
  CREATE UNIQUE INDEX "HR"."LOC_ID_PK" ON "HR"."LOCATIONS" ("LOCATION_ID") 
  ;
ALTER TABLE "HR"."LOCATIONS" ADD CONSTRAINT "LOC_ID_PK" PRIMARY KEY ("LOCATION_ID")
  USING INDEX "HR"."LOC_ID_PK"  ENABLE;

COMMENT ON TABLE "HR"."LOCATIONS" IS 'Locations table that contains specific address of a specific office,
warehouse, and/or production site of a company. Does not store addresses /
locations of customers. references with the departments and countries tables. ';
COMMENT ON COLUMN "HR"."LOCATIONS"."CITY" IS 'A not null column that shows city where an office, warehouse, or 
production site of a company is located. ';
COMMENT ON COLUMN "HR"."LOCATIONS"."COUNTRY_ID" IS 'Country where an office, warehouse, or production site of a company is
located. Foreign key to country_id column of the countries table.';
COMMENT ON COLUMN "HR"."LOCATIONS"."LOCATION_ID" IS 'Primary key of locations table';
COMMENT ON COLUMN "HR"."LOCATIONS"."POSTAL_CODE" IS 'Postal code of the location of an office, warehouse, or production site 
of a company. ';
COMMENT ON COLUMN "HR"."LOCATIONS"."STATE_PROVINCE" IS 'State or Province where an office, warehouse, or production site of a 
company is located.';
COMMENT ON COLUMN "HR"."LOCATIONS"."STREET_ADDRESS" IS 'Street address of an office, warehouse, or production site of a company.
Contains building number and street name';

