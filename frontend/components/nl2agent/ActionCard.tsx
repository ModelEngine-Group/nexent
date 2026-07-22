"use client";

import React from "react";

export const ActionCard: React.FC<{
  title: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}> = ({ title, children, className = "" }) => (
  <section
    className={`my-3 rounded-lg border border-gray-200 bg-white p-4 ${className}`.trim()}
  >
    <h3 className="mb-3 text-sm font-medium">{title}</h3>
    {children}
  </section>
);

export const StaticFieldList: React.FC<{
  fields: Array<{
    key: string;
    label: React.ReactNode;
    value: React.ReactNode;
  }>;
}> = ({ fields }) => (
  <dl className="space-y-3">
    {fields.map((field) => (
      <div key={field.key}>
        <dt className="text-xs font-medium text-gray-500">{field.label}</dt>
        <dd className="mt-0.5 whitespace-pre-wrap text-sm text-gray-800">
          {field.value}
        </dd>
      </div>
    ))}
  </dl>
);
