#!/usr/bin/perl

use strict;
use warnings;

use DBI;
require "./conf.pl";

our($db,$db_user,$db_pwd);
my $con;
my $query_mode = 0;
my $content = "";
my $search_string = "";

if ( exists $ENV{"QUERY_STRING"} ) {

	if ( $ENV{"QUERY_STRING"} =~ /\&?q=([^&]+)\&?/ ) {

		$search_string = $1;
		$search_string =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;	
		
		if ( length($search_string) > 0 ) {
			#adm no. search
			if ($search_string =~ /^\d+$/) {
				$query_mode = 1;
			}
			#name search, possib space separated
			else {
				$query_mode = 2;
			}	
		}
	}
}

#if I'm going to do any searches,
#will need this lookup one way or the other
my %table_name_class_lookup = ();

if ($query_mode) {

	my @today = localtime;
	my $current_yr = $today[5] + 1900;

	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});
	my $prep_stmt2 = $con->prepare("SELECT table_name,class,start_year,grad_year FROM student_rolls");

	if ($prep_stmt2) {

		my $rc = $prep_stmt2->execute();
		if ($rc) {	
			while ( my @rslts = $prep_stmt2->fetchrow_array() ) {

				my $class = $rslts[1];
				my $class_yr = ($current_yr - $rslts[2]) + 1;
				
				$class =~ s/\d+/$class_yr/;

				#already graduated?
				if ($rslts[3] < $current_yr) {

					$class_yr = ($rslts[3] - $rslts[2])+1;
					$class =~ s/\d+/$class_yr/;

					$class .= "($rslts[3])";
				}
				$table_name_class_lookup{$rslts[0]} = $class;
			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM adms: ", $prep_stmt2->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM adms: ", $prep_stmt2->errstr, $/;
	}
}
my %results = ();

#check `adms` table for this student
if ($query_mode == 1) {

	if ($con) {

		my %table_adm_lookup = ();

		my $prep_stmt0 = $con->prepare("SELECT adm_no,table_name FROM adms WHERE adm_no LIKE ?");
		if ($prep_stmt0) {
			my $rc = $prep_stmt0->execute($search_string . "%");
			if ($rc) {	
				while ( my @rslts = $prep_stmt0->fetchrow_array() ) {
					$table_adm_lookup{$rslts[1]}->{$rslts[0]}++;
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM adms: ", $prep_stmt0->errstr, $/;
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM adms: ", $prep_stmt0->errstr, $/;
		}

		if ( scalar(keys %table_adm_lookup) > 0 ) {

			for my $table ( keys %table_adm_lookup ) {

				my @adms = keys %{$table_adm_lookup{$table}};
				my @where_clause_bts = ();
			
				foreach (@adms) {
					push @where_clause_bts, "adm=?"
				}

				my $where_clause = join(" OR ", @where_clause_bts);

				my $prep_stmt1 = $con->prepare("SELECT adm,s_name,o_names FROM `$table` WHERE $where_clause");

				if ($prep_stmt1) {

					my $rc = $prep_stmt1->execute(@adms);
					if ($rc) {	
						while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

							my $name = $rslts[1] . " " . $rslts[2];
							my $class = $table_name_class_lookup{$table};

							my $formatted_result = sprintf("%-8s&nbsp;&nbsp;%s&nbsp;&nbsp;%s", $rslts[0], $name, $class);
							$results{$rslts[0]} = $formatted_result;
						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM adms: ", $prep_stmt1->errstr, $/;
					}
				}
				else {
					print STDERR "Couldn't prepare SELECT FROM adms: ", $prep_stmt1->errstr, $/;
				}
			}

		}
	}
}

#name search
elsif ($query_mode == 2) {

	my @search_string_bts = split/\+/, $search_string;

	my @bind_vals = ();
	my @where_clause_bts = ();

	for my $search_str_bt ( @search_string_bts ) {

		push @where_clause_bts, "s_name LIKE ?";
		push @where_clause_bts, "o_names LIKE ?";

		push @bind_vals, ($search_str_bt . "%", $search_str_bt . "%");
	}

	my $where_clause = join(" OR ", @where_clause_bts);

	for my $table ( keys %table_name_class_lookup ) {

		my $prep_stmt3 = $con->prepare("SELECT adm,s_name,o_names FROM `$table` WHERE $where_clause");

		if ($prep_stmt3) {

			my $rc = $prep_stmt3->execute(@bind_vals);
			if ($rc) {	
				while ( my @rslts = $prep_stmt3->fetchrow_array() ) {

					my $name = $rslts[1] . " " . $rslts[2];
					my $class = $table_name_class_lookup{$table};

					my $formatted_result = sprintf("%-8s&nbsp;&nbsp;%s&nbsp;&nbsp;%s", $rslts[0], $name, $class);
					$results{$rslts[0]} = $formatted_result;
				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM adms: ", $prep_stmt3->errstr, $/;
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM adms: ", $prep_stmt3->errstr, $/;
		}
	}
}
if (keys %results) {
	for my $adm (sort {$b <=> $a} keys %results) {
		$content .= $results{$adm} . "\$";
	}
}

print "Status: 200 OK\r\n";
print "Content-Type: text/plain; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

print "\r\n";
print $content;

$con->disconnect() if ($con);
