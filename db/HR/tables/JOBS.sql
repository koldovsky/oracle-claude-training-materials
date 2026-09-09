CREATE TABLE "HR"."JOBS" 
   (	"JOB_ID" VARCHAR2(10) COLLATE "USING_NLS_COMP", 
	"JOB_TITLE" VARCHAR2(35) COLLATE "USING_NLS_COMP" CONSTRAINT "JOB_TITLE_NN" NOT NULL ENABLE, 
	"MIN_SALARY" NUMBER(6,0), 
	"MAX_SALARY" NUMBER(6,0)
   )  DEFAULT COLLATION "USING_NLS_COMP" ;
  CREATE UNIQUE INDEX "HR"."JOB_ID_PK" ON "HR"."JOBS" ("JOB_ID") 
  ;
ALTER TABLE "HR"."JOBS" ADD CONSTRAINT "JOB_ID_PK" PRIMARY KEY ("JOB_ID")
  USING INDEX "HR"."JOB_ID_PK"  ENABLE;

COMMENT ON TABLE "HR"."JOBS" IS 'jobs table with job titles and salary ranges.
References with employees and job_history table.';
COMMENT ON COLUMN "HR"."JOBS"."JOB_ID" IS 'Primary key of jobs table.';
COMMENT ON COLUMN "HR"."JOBS"."JOB_TITLE" IS 'A not null column that shows job title, e.g. AD_VP, FI_ACCOUNTANT';
COMMENT ON COLUMN "HR"."JOBS"."MAX_SALARY" IS 'Maximum salary for a job title';
COMMENT ON COLUMN "HR"."JOBS"."MIN_SALARY" IS 'Minimum salary for a job title.';

